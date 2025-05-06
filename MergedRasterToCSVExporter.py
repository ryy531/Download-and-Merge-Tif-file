import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from osgeo import gdal
import pandas as pd
import numpy as np
import threading
import queue # Import queue for thread-safe communication

"""
This script consolidates data from multiple gender/age population TIFFs
into a CSV, starting directly from a base Total Population TIFF.
It extracts points and Total Population from the base TIFF, then adds
columns from other gender/age TIFFs based on those points.
It uses a GUI panel with buttons, path displays, a status label,
and a progress bar, running processing in a background thread.
"""

# Use a queue for messages from the thread to the GUI
message_queue = queue.Queue()

def parse_total_pop_tif_name(tif_name):
    """
    Parse Total Population TIFF file name into components:
    country, year, and the rest as suffix part.
    Expected format: country_ppp_year_... (e.g., BEL_ppp_2020_UNadj_constrained.tif)

    Parameters:
    tif_name (str): The base name of the TIFF file without extension.

    Returns:
    tuple: (country, year, suffix_part)
           suffix_part includes the leading underscore if parts > 3
    Raises:
        ValueError: if tif_name cannot be split into at least 3 parts (country, ppp, year)
    """
    parts = tif_name.split("_")
    if len(parts) < 3:
         raise ValueError(f"Invalid tif_name: {tif_name}, expected at least 3 parts (country_ppp_year...)")

    country = parts[0]
    # Check if the second part is 'ppp' or similar population indicator
    if parts[1] != 'ppp':
         print(f"Warning: Second part of '{tif_name}' is not 'ppp'. Assuming third part ('{parts[2]}') is the year.")

    year = parts[2] # Assumes year is the third part (index 2)
    suffix_part = "_" + "_".join(parts[3:]) if len(parts) > 3 else ""
    return country, year, suffix_part

def parse_gender_age_tif_name(tif_name):
    """
    Parse Gender/Age/Other TIFF file name into components:
    country, gender, age, year, and the rest as suffix part.
    Expected format: country_gender_age_year_... (e.g., BEL_f_0_2020_...)

    Parameters:
    tif_name (str): The base name of the TIFF file without extension.

    Returns:
    tuple: (country, gender, age, year, suffix_part)
           gender will be '', age will be '' if less than 3 parts
           year will be '', suffix_part will be '' if less than 4 parts
           suffix_part includes the leading underscore if parts > 4
    Raises:
        ValueError: if tif_name cannot be split into at least 3 parts (country_gender_age...)
    """
    parts = tif_name.split("_")
    if len(parts) < 3:
         raise ValueError(f"Invalid tif_name: {tif_name}, expected at least 3 parts (country_gender_age...)")

    country = parts[0]
    gender = parts[1]
    age = parts[2]
    year = parts[3] if len(parts) > 3 else ""
    suffix_part = "_" + "_".join(parts[4:]) if len(parts) > 4 else ""

    return country, gender, age, year, suffix_part


def pixel_to_xy_centroid(row, col, gt):
    """
    Convert pixel indices (col, row) to centroid map coordinates (x,y)
    using the geotransform.

    Parameters:
    row (int or np.ndarray): The row index (or array of indices).
    col (int or np.ndarray): The column index (or array of indices).
    gt (tuple): The geotransform of the raster (ulx, x_res, x_shear, uly, y_shear, y_res).

    Returns:
    tuple: (x, y) coordinates (or NumPy arrays of coordinates).
    """
    # gt = (ulx, x_res, x_shear, uly, y_shear, y_res)
    # X = gt[0] + P*gt[1] + L*gt[2]
    # Y = gt[3] + P*gt[4] + L*gt[5]
    # P is pixel (column), L is line (row)
    # For centroid, use P+0.5 and L+0.5

    x = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
    y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]

    return x, y


# --- Core Processing Logic (Runs in a separate thread) ---
# Removed callback parameters
def process_all_tifs_task(initial_tif_path, tif_folder, output_csv_path):
    """
    Main processing logic to be run in a separate thread.
    Communicates status, progress, completion, and errors via the message_queue.
    """
    def report_status(status_text):
         message_queue.put(("status", status_text))

    # Modified to only report value and maximum
    def report_progress(value, maximum):
         message_queue.put(("progress", (value, maximum)))

    def report_completion(output_file_path, skipped_files=None):
        message_queue.put(("complete", (output_file_path, skipped_files)))

    def report_error(error_message):
        message_queue.put(("error", error_message))
        report_progress(0, 100) # Reset progress on error

    try:
        # --- Step 1: Process Initial Total Population TIFF ---
        report_status("Processing initial Total Population TIFF...")
        report_progress(0, 100)

        initial_ds = None
        try:
            initial_ds = gdal.Open(initial_tif_path)
            if initial_ds is None:
                report_error(f"Error opening initial Total Population tif file: {initial_tif_path}")
                return

            gt_initial = initial_ds.GetGeoTransform()
            if gt_initial is None:
                initial_ds = None
                report_error("Error: Initial Total Population tif file does not contain georeferencing information.")
                return

            band_initial = initial_ds.GetRasterBand(1)
            if band_initial is None:
                 initial_ds = None
                 report_error("Error: No band found in initial Total Population tif file.")
                 return

            report_status("Reading initial raster data...")
            array_initial = band_initial.ReadAsArray()
            nodata_initial = band_initial.GetNoDataValue()

            # Determine Country, Year, Suffix from initial TIFF name for CSV
            initial_tif_name_full = os.path.basename(initial_tif_path).rsplit('.', 1)[0].strip()
            country = ""
            year = ""
            suffix_part = ""
            try:
                 country, year, suffix_part = parse_total_pop_tif_name(initial_tif_name_full)
            except ValueError as e:
                 print(f"Warning: Could not parse initial TIFF name '{initial_tif_name_full}' using total pop pattern: {e}. Country/Year columns may be empty.")
                 # Continue with empty country/year/suffix


        except Exception as e:
             report_error(f"Error accessing initial Total Population TIFF: {e}")
             return
        finally:
             if initial_ds: initial_ds = None # Close to free resources

        report_status("Calculating points from initial TIFF...")

        # Find valid pixels (not nodata)
        if nodata_initial is not None:
             if np.issubdtype(array_initial.dtype, np.floating):
                  valid_mask = ~np.isclose(array_initial, nodata_initial, equal_nan=False)
             else:
                  # Attempt to convert nodata value to array dtype for safe comparison
                  try:
                       nodata_comp = np.array(nodata_initial, dtype=array_initial.dtype).item()
                       valid_mask = (array_initial != nodata_comp)
                  except Exception:
                       # Fallback if dtype conversion or comparison fails
                       print(f"Warning: Could not reliably compare nodata value {nodata_initial} with array dtype {array_initial.dtype}. Treating all pixels as potentially valid.")
                       valid_mask = np.ones_like(array_initial, dtype=bool)

        else:
             valid_mask = np.ones_like(array_initial, dtype=bool) # All pixels are valid

        # Get row and column indices of valid pixels
        valid_rows, valid_cols = np.where(valid_mask)
        initial_total_population_values = array_initial[valid_mask]

        # Calculate x, y coordinates for the centroids of valid pixels
        x_coords, y_coords = pixel_to_xy_centroid(valid_rows, valid_cols, gt_initial)

        num_points = len(x_coords)
        if num_points == 0:
             report_error("No valid data points found in the initial Total Population TIFF.")
             return

        report_status(f"Found {num_points} valid points.")

        # --- Prepare initial DataFrame data ---
        # Store required data as numpy arrays for efficiency
        data_arrays = {
            'x': x_coords,
            'y': y_coords,
            'TotalPopulation': initial_total_population_values,
            # Keep row/col indices temporarily for extracting from other TIFFs
            '_row': valid_rows,
            '_col': valid_cols
        }

        # Clean up initial array
        del array_initial, valid_mask, initial_total_population_values, x_coords, y_coords, valid_rows, valid_cols
        report_progress(10, 100) # Indicate completion of initial TIFF processing phase

        # --- Step 2: Process each Gender/Age/Other TIFF file ---
        try:
            tif_files = [f for f in os.listdir(tif_folder) if f.lower().endswith(('.tif', '.tiff'))]
            gender_age_tif_paths = [os.path.join(tif_folder, f) for f in tif_files]
        except Exception as e:
            report_error(f"Error listing files in TIFF folder: {e}")
            # Continue with only initial data if folder listing fails
            gender_age_tif_paths = []

        num_gender_age_tifs = len(gender_age_tif_paths)
        report_status(f"Processing {num_gender_age_tifs} additional TIFF files...")

        skipped_files = []
        extracted_data_dict = {} # Dictionary to hold data for gender/age columns

        # Use this loop to drive the progress bar
        progress_start = 10 # Start progress bar after initial processing
        progress_range = 80 # Use 80% of the bar for TIFF processing loop
        progress_step = progress_range / max(1, num_gender_age_tifs)


        for i, tif_path in enumerate(gender_age_tif_paths):
            tif_name_full = os.path.basename(tif_path).rsplit('.', 1)[0].strip()
            col_name = ""
            current_progress = progress_start + int((i) * progress_step) # Calculate progress before processing starts for this file
            report_progress(current_progress, 100)


            try:
                report_status(f"Processing TIFF {i+1}/{num_gender_age_tifs}: {tif_name_full}")

                # Parse TIFF file name to get column name (gender_age or similar)
                # Use the gender/age parser as the default for files in the folder
                try:
                     # Check if it matches gender_age pattern first
                     _, gender, age, _, _ = parse_gender_age_tif_name(tif_name_full)
                     if not gender or not age:
                          # Handle cases like 'BEL_total_2020_...' which might be in the folder but aren't gender/age
                          # If gender/age parsing fails, try the total pop parser pattern?
                          # Or assume only gender_age files are relevant from the folder?
                          # Let's require gender/age format for files in the folder for now.
                          raise ValueError("Gender or age part missing or name format unexpected for gender/age TIFF")

                     col_name = f"{gender}_{age}"
                     if col_name in data_arrays or col_name in extracted_data_dict: # Check against already added columns or existing extracted data
                          print(f"Warning: Column '{col_name}' derived from '{tif_name_full}' already exists. Skipping this TIFF.")
                          skipped_files.append(f"{tif_name_full} (Column '{col_name}' exists)")
                          continue # Skip this file

                except ValueError as e:
                    print(f"Warning: Skipping {tif_name_full} due to parsing error or invalid name format: {e}")
                    skipped_files.append(f"{tif_name_full} (Parsing error)")
                    continue # Skip this file


                ds = None
                try:
                    ds = gdal.Open(tif_path)
                    if ds is None:
                        print(f"Error opening tif file: {tif_path}") # Print to console as warning
                        skipped_files.append(f"{tif_name_full} (Error opening)")
                        continue # Skip this file

                    gt = ds.GetGeoTransform()
                    # Optional: Check if geotransform matches the initial one
                    if gt != gt_initial:
                         print(f"Warning: {tif_name_full} geotransform does not match initial. Results may be inaccurate.")


                    band = ds.GetRasterBand(1)
                    if band is None:
                        print(f"Error: No band found in {tif_path}") # Print to console as warning
                        skipped_files.append(f"{tif_name_full} (No band)")
                        continue # Skip this file

                    nodatavalue = band.GetNoDataValue()
                    array = band.ReadAsArray()

                except Exception as e:
                     print(f"Error accessing band/array for {tif_name_full}: {e}")
                     skipped_files.append(f"{tif_name_full} (Access error)")
                     continue # Skip this file
                finally:
                     if ds: ds = None # Close dataset to free resources


                # Extract values using the stored indices (_row, _col)
                rows_idx = data_arrays['_row']
                cols_idx = data_arrays['_col']

                # Create a mask for valid indices within *this* TIFF's array bounds
                rows_tif, cols_tif = array.shape
                mask_within_bounds = (rows_idx >= 0) & (rows_idx < rows_tif) & \
                                     (cols_idx >= 0) & (cols_idx < cols_tif)

                # Handle points that are outside the current TIFF's bounds
                extracted_values = np.full(num_points, np.nan, dtype=float) # Default to NaN

                if np.any(mask_within_bounds):
                    valid_rows_for_this_tif = rows_idx[mask_within_bounds]
                    valid_cols_for_this_tif = cols_idx[mask_within_bounds]

                    values_from_tif = array[valid_rows_for_this_tif, valid_cols_for_this_tif]

                    # Handle nodata values from the current TIFF
                    if nodatavalue is not None:
                         if np.issubdtype(values_from_tif.dtype, np.floating):
                              is_nodata = np.isclose(values_from_tif, nodatavalue, equal_nan=False)
                         else:
                              # Attempt to convert nodata value to array dtype for safe comparison
                              try:
                                   nodata_comp = np.array(nodatavalue, dtype=values_from_tif.dtype).item()
                                   is_nodata = (values_from_tif == nodata_comp)
                              except Exception:
                                   # Fallback if dtype conversion or comparison fails
                                   # Treat as no nodata match
                                   is_nodata = np.zeros_like(values_from_tif, dtype=bool)

                         values_from_tif = np.where(~is_nodata, values_from_tif, np.nan)

                    # Place extracted values into the correct positions in the full array
                    extracted_values[mask_within_bounds] = values_from_tif

                # Store the extracted data for this column
                extracted_data_dict[col_name] = extracted_values

            except Exception as e:
                 print(f"Unexpected error processing {tif_name_full}: {e}")
                 skipped_files.append(f"{tif_name_full} (Unexpected error: {e})")
                 continue # Skip this file

        # Update progress after the loop finishes
        report_progress(progress_start + progress_range, 100) # Ensure progress bar hits the end of this phase

        # --- Step 3: Create and Save Final DataFrame ---
        report_status("Creating final DataFrame...")

        # Build the final DataFrame from the collected NumPy arrays
        final_data = {
             'Country': np.full(num_points, country, dtype=object), # Use object dtype for strings
             'Year': np.full(num_points, year, dtype=object),
             'x': data_arrays['x'],
             'y': data_arrays['y'],
             'TotalPopulation': data_arrays['TotalPopulation']
        }
        # Add extracted gender/age columns
        final_data.update(extracted_data_dict)

        # Use the dictionary to create DataFrame directly - more efficient
        df = pd.DataFrame(final_data)

        # Drop temporary columns
        df = df.drop(columns=['_row', '_col'], errors='ignore') # Use errors='ignore' in case they weren't added

        # Sort gender/age columns (f_* and m_*)
        gender_age_cols = [col for col in df.columns if col.startswith(('f_', 'm_'))]
        def sort_key(col):
            try:
                parts = col.split('_')
                if len(parts) == 2:
                    gender_prefix = parts[0]
                    age_str = parts[1]
                    # Handle age ranges like '80plus' or '80_plus' if necessary
                    # For now, assume numeric age or simple 'plus'
                    if age_str.lower() == 'plus' or age_str.lower().endswith('plus'):
                         # Put 'plus' ages at the end of their gender group
                         base_age_str = age_str.lower().replace('plus', '').replace('_', '')
                         base_age = int(base_age_str) if base_age_str.isdigit() else 999
                         return (gender_prefix, base_age + 1000) # Add a large number to push it after numeric ages
                    else:
                         return (gender_prefix, int(age_str))
            except ValueError:
                pass # Fallback if age part isn't a number or expected plus format
            # General sorting for columns that couldn't be parsed with age number
            if col.startswith('f_'):
                return ('f', col) # Sort alphabetically within 'f_' group
            elif col.startswith('m_'):
                return ('m', col) # Sort alphabetically within 'm_' group
            else:
                return ('other', col) # Should not happen if logic is correct, but as a fallback

        sorted_gender_age_cols = sorted(gender_age_cols, key=sort_key)

        # Define final column order
        fixed_cols = ['Country', 'Year', 'x', 'y', 'TotalPopulation']
        all_present_cols = df.columns.tolist()
        final_cols = [col for col in fixed_cols if col in all_present_cols] + \
                     [col for col in sorted_gender_age_cols if col in all_present_cols]

        # Add any other columns that might exist and weren't explicitly handled (shouldn't be any in this flow)
        existing_other_cols = [col for col in all_present_cols if col not in final_cols]
        final_cols.extend(existing_other_cols)

        # Reindex the DataFrame to the final column order
        df = df[final_cols]

        # --- Save updated CSV using pandas' efficient method ---
        report_status("Saving updated CSV...")
        report_progress(95, 100)

        try:
            df.to_csv(output_csv_path, index=False, encoding='utf-8')
        except Exception as e:
            report_error(f"Error saving output CSV file:\n{e}")
            return

        # Clean up final pandas DataFrame to save memory
        del df

        report_progress(100, 100)
        report_completion(output_csv_path, skipped_files) # Signal success

    except Exception as e:
        # Catch any unexpected errors during the main flow of the task setup or intermediate steps
        import traceback
        traceback.print_exc() # Print full traceback to console for debugging
        report_error(f"An unexpected error occurred during processing task: {str(e)}")
        report_progress(0, 100) # Reset progress on error


# --- GUI Application Class ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Process TIFFs to CSV")
        # self.geometry("600x450") # Give it a reasonable initial size

        self.initial_tif_path = None
        self.tif_folder = None
        self.output_csv_path = None
        self.processing_thread = None

        self.create_widgets()
        self.check_queue() # Start checking the message queue periodically

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Adjust window size based on widgets after creation
        self.update_idletasks()
        self.geometry(self.winfo_geometry()) # Set size to fit widgets
        self.minsize(self.winfo_width(), self.winfo_height()) # Prevent shrinking too much


    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(expand=True, fill="both")

        # Configure grid for the frame
        main_frame.columnconfigure(1, weight=1) # Path labels column expands
        # Adjust row weights
        for i in range(8): # Rows for selectors (0-2), separator (3), button (4), progress (5), status (6)
            main_frame.rowconfigure(i, weight=0)

        # Input Total Population TIFF Selection
        ttk.Label(main_frame, text="Total Population TIFF:").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        self.initial_tif_label = ttk.Label(main_frame, text="No file selected", foreground="gray")
        self.initial_tif_label.grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_initial_tif).grid(row=0, column=2, sticky="e", pady=2, padx=5)

        # Input TIFF Folder Selection (Gender/Age/Other TIFFs)
        ttk.Label(main_frame, text="Additional TIFFs Folder:").grid(row=1, column=0, sticky="w", pady=2, padx=5)
        self.tif_folder_label = ttk.Label(main_frame, text="No folder selected", foreground="gray")
        self.tif_folder_label.grid(row=1, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_tif_folder).grid(row=1, column=2, sticky="e", pady=2, padx=5)

        # Output CSV File Selection
        ttk.Label(main_frame, text="Output CSV:").grid(row=2, column=0, sticky="w", pady=2, padx=5)
        self.output_csv_label = ttk.Label(main_frame, text="No path selected", foreground="gray")
        self.output_csv_label.grid(row=2, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_output_csv).grid(row=2, column=2, sticky="e", pady=2, padx=5)

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)

        # Process Button
        self.process_button = ttk.Button(main_frame, text="Start Processing", command=self.start_processing)
        self.process_button.grid(row=4, column=0, columnspan=3, pady=10)

        # Progress Bar
        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=5, padx=5)

        # Status Label
        self.status_label = ttk.Label(main_frame, text="Ready.")
        self.status_label.grid(row=6, column=0, columnspan=3, sticky="w", pady=5, padx=5)


    def select_initial_tif(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select Total Population TIFF File (Base Data & GeoTransform)",
            filetypes=[("TIFF files", "*.tif *.tiff")]
        )
        if file_path:
            self.initial_tif_path = file_path
            self.initial_tif_label.config(text=os.path.basename(file_path), foreground="black")
            self.suggest_output_csv()


    def select_tif_folder(self):
        folder_path = filedialog.askdirectory(
            parent=self,
            title="Select Folder Containing Additional Gender/Age TIFFs"
        )
        if folder_path:
            self.tif_folder = folder_path
            self.tif_folder_label.config(text=os.path.basename(folder_path), foreground="black")
            # We could potentially suggest output based on the first file in the folder too,
            # but prioritizing the initial_tif_path is better as it's required.
            # self.suggest_output_csv()


    def suggest_output_csv(self):
         # Suggest output path if Initial TIF is selected, and output isn't already chosen manually
         if self.initial_tif_path and (not self.output_csv_path or self.output_csv_label.cget("foreground") == "gray"):
             default_name = 'output.csv'
             initial_dir = os.path.expanduser("~")

             try:
                  if os.path.exists(self.initial_tif_path):
                       initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                       # Use the Total Pop specific parser
                       country, year, suffix_part = parse_total_pop_tif_name(initial_tif_name)
                       # Construct the desired output name format: country_year_suffix.csv
                       # suffix_part already includes the leading underscore if present
                       default_name = f"{country}_{year}{suffix_part}.csv" if country and year else default_name
                       initial_dir = os.path.dirname(self.initial_tif_path)

             except ValueError:
                  pass # If parsing fails, just use default 'output.csv' and home dir
             except Exception:
                  pass # Handle other potential errors

             # Construct the suggested path and update the label if a better name/dir was found
             default_output_path = os.path.join(initial_dir, default_name)
             # Only suggest if it's a different path or the label was gray
             if self.output_csv_path != default_output_path or self.output_csv_label.cget("foreground") == "gray":
                  self.output_csv_path = default_output_path
                  self.output_csv_label.config(text=os.path.basename(default_output_path), foreground="black")


    def select_output_csv(self):
        default_name = 'output.csv'
        initial_dir = os.path.expanduser("~") # Default to home directory

        # Try to get a sensible default name and directory based on the initial TIFF
        if self.initial_tif_path and os.path.exists(self.initial_tif_path):
             initial_dir = os.path.dirname(self.initial_tif_path)
             try:
                  initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                  # Use the Total Pop specific parser
                  country, year, suffix_part = parse_total_pop_tif_name(initial_tif_name)
                  # Construct the desired output name format: country_year_suffix.csv
                  default_name = f"{country}_{year}{suffix_part}.csv" if country and year else default_name
             except ValueError:
                  pass # If parsing fails, use default 'output.csv'
             except Exception:
                  pass


        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Output CSV As",
            initialdir=initial_dir,
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if file_path:
            self.output_csv_path = file_path
            self.output_csv_label.config(text=os.path.basename(file_path), foreground="black")

    def start_processing(self):
        # Validation
        if not self.initial_tif_path or not os.path.exists(self.initial_tif_path):
             messagebox.showwarning("Warning", "Please select a valid Total Population TIFF file.", parent=self)
             return
        if not self.tif_folder or not os.path.isdir(self.tif_folder):
            messagebox.showwarning("Warning", "Please select a valid folder containing additional TIFFs.", parent=self)
            return
        if not self.output_csv_path:
            messagebox.showwarning("Warning", "Please select an Output CSV file path.", parent=self)
            return

        # Ensure the output directory exists
        output_dir = os.path.dirname(self.output_csv_path)
        if output_dir and not os.path.exists(output_dir):
             try:
                  os.makedirs(output_dir)
             except OSError as e:
                  messagebox.showerror("Error", f"Could not create output directory {output_dir}:\n{e}", parent=self)
                  return

        # Check if a thread is already running
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showinfo("Info", "Processing is already running.", parent=self)
            return

        # Disable button and update status/progress
        self.process_button.config(state="disabled")
        self.status_label.config(text="Processing started...")
        self.progress.config(mode="determinate", value=0, maximum=100)

        # Create and start the worker thread
        # No longer passing GUI methods as arguments
        self.processing_thread = threading.Thread(target=process_all_tifs_task,
                                                args=(self.initial_tif_path,
                                                      self.tif_folder,
                                                      self.output_csv_path))
        self.processing_thread.daemon = True # Allow main process to exit
        self.processing_thread.start()

    # --- Thread-Safe Communication via Queue ---
    def check_queue(self):
        """Check the message queue for updates from the worker thread."""
        try:
            # Process all messages currently in the queue
            while not message_queue.empty():
                message_type, data = message_queue.get_nowait()

                if message_type == "status":
                    status_text = data
                    self._do_update_status(status_text)
                elif message_type == "progress":
                    value, maximum = data
                    self._do_update_progress(value, maximum)
                elif message_type == "complete":
                    output_file_path, skipped_files = data
                    self._do_processing_complete(output_file_path, skipped_files)
                elif message_type == "error":
                    error_message = data
                    self._do_processing_error(error_message)

        except queue.Empty:
            # No messages in the queue, this is the normal state most of the time
            pass
        finally:
            # Schedule the next check regardless of whether messages were processed
            self.after(100, self.check_queue) # Check every 100 ms

    # --- Actual GUI Update Methods (called by check_queue in main thread) ---

    def _do_update_progress(self, value, maximum):
        """Performs the actual GUI progress update in the main thread."""
        try:
            if self.progress.winfo_exists():
                 # Only update if maximum is positive to avoid errors with value > 0 and max=0
                 if maximum > 0:
                      self.progress.config(maximum=maximum, value=value)
                 else:
                      # Handle cases where max is 0 (e.g., no additional files) - maybe indeterminate mode?
                      # For simplicity, just set value to 0 if max is 0
                       self.progress.config(value=0)
        except tk.TclError:
            pass # Widget might have been destroyed

    def _do_update_status(self, status_text):
         """Performs the actual GUI status update in the main thread."""
         try:
            if self.status_label.winfo_exists():
                 self.status_label.config(text=status_text)
         except tk.TclError:
            pass # Widget might have been destroyed


    def _do_processing_complete(self, output_file_path, skipped_files):
        """Performs final actions in the main thread after success."""
        try:
            final_status_text = "Processing complete."
            if skipped_files:
                 final_status_text += f" (Skipped {len(skipped_files)} file(s))"
                 print("\nSkipped files:")
                 for f in skipped_files:
                      print(f"- {f}")
                 print("-" * 20) # Separator in console output

            if self.status_label.winfo_exists():
                 self.status_label.config(text=final_status_text)
            if self.progress.winfo_exists():
                 self.progress.config(value=100) # Ensure progress bar is full
            if self.process_button.winfo_exists():
                 self.process_button.config(state="normal") # Re-enable the button

            # Show success message
            msg = f"CSV file successfully created:\n{output_file_path}"
            if skipped_files:
                 msg += f"\n\nNote: {len(skipped_files)} file(s) were skipped due to errors or invalid names. Check console for details."
            messagebox.showinfo("Success", msg, parent=self)

        except tk.TclError:
            pass

    def _do_processing_error(self, error_message):
        """Performs final actions and shows error in the main thread."""
        try:
            if self.status_label.winfo_exists():
                 self.status_label.config(text="Error occurred.")
            if self.progress.winfo_exists():
                 self.progress.config(mode="determinate", value=0) # Reset progress on error
            if self.process_button.winfo_exists():
                 self.process_button.config(state="normal") # Re-enable the button

            # Show error message
            messagebox.showerror("Error", error_message, parent=self)
        except tk.TclError:
            pass

    def on_closing(self):
        """Handles the window closing event."""
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askyesno("Quit", "Processing is still running. Are you sure you want to quit?", parent=self):
                # Clean up queue before destroying
                while not message_queue.empty():
                     try:
                         message_queue.get_nowait()
                     except queue.Empty:
                         pass
                self.destroy() # Destroy the main window
        else:
            self.destroy() # Destroy the main window


# Main execution block
if __name__ == "__main__":
    # Suppress GDAL warnings
    gdal.SetConfigOption('CPL_REDIRECT_STDERR', 'NO')
    gdal.SetConfigOption('CPL_SUPRESS_GDAL_DATA_WARNING', 'YES')

    app = App()
    app.mainloop() # Start the main Tkinter event loop
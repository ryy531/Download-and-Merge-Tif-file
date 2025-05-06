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
into an initial CSV (output from step2), based on point coordinates.
It uses a GUI panel with buttons, path displays, a status label,
and runs processing in a background thread to keep the GUI responsive.
Progress bar functionality has been removed for simplicity and performance.
"""

# Use a queue for messages from the thread to the GUI
message_queue = queue.Queue()

def parse_tif_name(tif_name):
    """
    Parse TIFF file name into components: country, gender, age, year, suffix.

    Parameters:
    tif_name (str): The base name of the TIFF file without extension.

    Returns:
    tuple: (country, gender, age, year, suffix)
           gender will be '', age will be '' if less than 4 parts
           suffix will be '' if less than 5 parts
    Raises:
        ValueError: if tif_name cannot be split into at least 4 parts
    """
    parts = tif_name.split("_")
    if len(parts) < 4:
         raise ValueError(f"Invalid tif_name: {tif_name}, expected at least 4 parts")

    country = parts[0]
    gender = parts[1]
    age = parts[2]
    year = parts[3]
    suffix = "_".join(parts[4:]) if len(parts) > 4 else ""
    return country, gender, age, year, suffix

def xy_to_pixel(x, y, gt):
    """
    Convert map coordinates (x,y) to pixel indices (col, row) using the geotransform.

    Parameters:
    x (float): The x-coordinate.
    y (float): The y-coordinate.
    gt (tuple): The geotransform of the raster.

    Returns:
    tuple: The pixel indices (col, row). Returns None if gt is invalid or cannot be inverted.
    """
    # gt = (ulx, x_res, x_shear, uly, y_shear, y_res)
    # X = gt[0] + P*gt[1] + L*gt[2]
    # Y = gt[3] + P*gt[4] + L*gt[5]
    # P is pixel (column), L is line (row)

    # Calculate inverse geotransform
    det = gt[1] * gt[5] - gt[2] * gt[4] # Determinant
    if det == 0:
         return None # Cannot invert geotransform

    inv_det = 1 / det

    # Solve for P (pixel) and L (line)
    pixel_float = (gt[5] * (x - gt[0]) - gt[2] * (y - gt[3])) * inv_det
    line_float = (gt[1] * (y - gt[3]) - gt[4] * (x - gt[0])) * inv_det

    # Convert to integer indices (0-based) by truncation
    col = int(pixel_float)
    row = int(line_float)

    return col, row

# --- Core Processing Logic (Runs in a separate thread) ---
def process_tifs_task(initial_csv_path, initial_tif_path, tif_folder, output_csv_path):
    """
    Main processing logic to be run in a separate thread.
    Communicates status via the message_queue.
    """
    # Renamed report_progress to report_status as we only have status updates now
    def report_status(status_text):
         message_queue.put(("status", status_text))

    def report_completion(output_file_path, skipped_files=None):
        message_queue.put(("complete", (output_file_path, skipped_files)))

    def report_error(error_message):
        message_queue.put(("error", error_message))

    try:
        # --- Setup and Initial Read ---
        report_status("Reading initial CSV...")
        try:
            df = pd.read_csv(initial_csv_path)
        except Exception as e:
            report_error(f"Error reading initial CSV file:\n{e}")
            return

        required_initial_cols = ['x', 'y', 'TotalPopulation']
        for col in required_initial_cols:
            if col not in df.columns:
                report_error(f"Error: Column '{col}' not found in initial CSV")
                return

        report_status("Getting geotransform from initial TIFF...")
        initial_ds = None
        try:
            initial_ds = gdal.Open(initial_tif_path)
            if initial_ds is None:
                report_error(f"Error opening initial tif file: {initial_tif_path}")
                return
            gt_initial = initial_ds.GetGeoTransform()
            if gt_initial is None:
                report_error("Error: Initial tif file does not contain georeferencing information.")
                return

        except Exception as e:
             report_error(f"Error accessing initial TIFF: {e}")
             return
        finally:
             if initial_ds: initial_ds = None # Close to free resources

        report_status("Calculating pixel coordinates...")
        pixel_coords_series = df.apply(lambda row: xy_to_pixel(row['x'], row['y'], gt_initial), axis=1)

        # Check for any None results
        if pixel_coords_series.isnull().any():
             num_failed = pixel_coords_series.isnull().sum()
             report_error(f"Failed to calculate pixel coordinates for {num_failed} points. Check initial TIFF georeferencing.")
             return # Stop processing if coordinate calculation fails

        df['col'], df['row'] = zip(*pixel_coords_series.tolist())

        # Get list of tif files in the folder
        try:
            tif_files = [f for f in os.listdir(tif_folder) if f.lower().endswith(('.tif', '.tiff'))]
            tif_paths = [os.path.join(tif_folder, f) for f in tif_files]
        except Exception as e:
            report_error(f"Error listing files in TIFF folder: {e}")
            return

        if not tif_paths:
            report_status("No TIFF files found in the selected folder. Output CSV will contain only initial data.")
            # Continue to save the initial data if no TIFFs are found
            num_tifs = 0
        else:
            num_tifs = len(tif_paths)


        skipped_files = []

        # Determine base country and year for output CSV filename and columns
        country = ""
        year = ""
        found_base_info = False
        for tif_path in tif_paths:
             tif_name_full = os.path.basename(tif_path).rsplit('.', 1)[0].strip()
             try:
                  current_country, _, _, current_year, _ = parse_tif_name(tif_name_full)
                  country = current_country
                  year = current_year
                  found_base_info = True
                  break # Found the first parsable file, use its info
             except ValueError:
                  continue # Try next file

        # Fallback to initial tif name if no TIFFs in folder or none were parsable
        if not found_base_info and initial_tif_path and os.path.exists(initial_tif_path):
             try:
                  initial_tif_name_full = os.path.basename(initial_tif_path).rsplit('.', 1)[0].strip()
                  country, _, _, year, _ = parse_tif_name(initial_tif_name_full)
                  found_base_info = True
             except ValueError:
                  pass # Cannot get info from initial TIFF name either


        # --- Process each TIFF file ---
        report_status(f"Processing {num_tifs} TIFF files...")

        for i, tif_path in enumerate(tif_paths):
            tif_name_full = os.path.basename(tif_path).rsplit('.', 1)[0].strip()
            col_name = ""
            try:
                report_status(f"Processing TIFF {i+1}/{num_tifs}: {tif_name_full}")

                # Parse TIFF file name to get column name (gender_age)
                _, gender, age, _, _ = parse_tif_name(tif_name_full)
                if not gender or not age:
                     raise ValueError("Gender or age part missing for column name") # Ensure gender and age exist

                col_name = f"{gender}_{age}"

                if col_name in df.columns:
                     print(f"Warning: Column '{col_name}' already exists. Skipping TIFF {tif_name_full}")
                     skipped_files.append(f"{tif_name_full} (Column exists)")
                     continue # Skip this file

                ds = None
                try:
                    ds = gdal.Open(tif_path)
                    if ds is None:
                        print(f"Error opening tif file: {tif_path}") # Print to console as warning
                        skipped_files.append(f"{tif_name_full} (Error opening)")
                        continue # Skip this file

                    gt = ds.GetGeoTransform()
                    if gt != gt_initial:
                        print(f"Warning: {tif_name_full} geotransform does not match initial. Results may be inaccurate.")

                    rows_tif = ds.RasterYSize
                    cols_tif = ds.RasterXSize
                    band = ds.GetRasterBand(1)
                    if band is None:
                        print(f"Error: No band found in {tif_path}") # Print to console as warning
                        skipped_files.append(f"{tif_name_full} (No band)")
                        continue # Skip this file

                    nodatavalue = None
                    try:
                        nodatavalue = band.GetNoDataValue()
                        # Attempt conversion to array dtype for accurate comparison later
                        if nodatavalue is not None:
                             # Read a single pixel to get array dtype then convert nodatavalue
                             temp_array = band.ReadAsArray(0, 0, 1, 1)
                             if temp_array is not None and temp_array.size > 0:
                                  nodatavalue = temp_array[0,0] * 0 + nodatavalue
                             else:
                                  nodatavalue = None # Cannot get dtype if array read fails/is empty
                    except Exception:
                        nodatavalue = None # Ignore if nodata not found or conversion fails

                    array = band.ReadAsArray()

                except Exception as e:
                     print(f"Error accessing band/array for {tif_name_full}: {e}")
                     skipped_files.append(f"{tif_name_full} (Access error)")
                     continue # Skip this file
                finally:
                     if ds: ds = None # Close dataset to free resources


                # Extract values using pre-calculated indices (col, row)
                cols_idx = df['col'].values.astype(int)
                rows_idx = df['row'].values.astype(int)

                values = np.full(len(df), np.nan, dtype=float) # Use NaN for missing values

                # Create a mask for valid indices within *this* TIFF's array bounds
                mask_within_bounds = (rows_idx >= 0) & (rows_idx < array.shape[0]) & \
                                     (cols_idx >= 0) & (cols_idx < array.shape[1])

                valid_rows_idx = rows_idx[mask_within_bounds]
                valid_cols_idx = cols_idx[mask_within_bounds]

                if len(valid_rows_idx) > 0:
                    extracted_values = array[valid_rows_idx, valid_cols_idx]

                    # Handle nodata values
                    if nodatavalue is not None:
                        if np.issubdtype(extracted_values.dtype, np.floating):
                             is_nodata = np.isclose(extracted_values, nodatavalue, equal_nan=False)
                        else:
                             # Ensure comparison value is same dtype if possible, fallback to direct comparison
                             if hasattr(nodatavalue, 'dtype') and extracted_values.dtype == nodatavalue.dtype:
                                  is_nodata = (extracted_values == nodatavalue)
                             else:
                                  # Fallback to direct comparison - might be less robust for floats
                                  try:
                                       is_nodata = (extracted_values == nodatavalue)
                                  except Exception:
                                       # Comparison failed (e.g., incompatible types), treat as no nodata match
                                       is_nodata = np.zeros_like(extracted_values, dtype=bool)


                        extracted_values = np.where(~is_nodata, extracted_values, np.nan)

                    values[mask_within_bounds] = extracted_values

                df[col_name] = values # Add the new column

            except ValueError as e:
                print(f"Warning: Skipping {tif_name_full} due to parsing error or invalid name format: {e}")
                skipped_files.append(f"{tif_name_full} (Parsing error)")
                continue # Skip this file

            except Exception as e:
                 print(f"Unexpected error processing {tif_name_full}: {e}")
                 skipped_files.append(f"{tif_name_full} (Unexpected error)")
                 continue # Skip this file


        # Add Country and Year columns based on the determination made earlier
        if found_base_info:
             df['Country'] = country
             df['Year'] = year
        else:
             # Add empty columns if country/year couldn't be determined
             df['Country'] = ""
             df['Year'] = ""

        # Drop temporary columns
        df = df.drop(['row', 'col'], axis=1)

        # Sort new columns (f_* and m_*)
        new_cols = [col for col in df.columns if col.startswith(('f_', 'm_'))]
        def sort_key(col):
            try:
                parts = col.split('_')
                if len(parts) == 2:
                    gender_prefix = parts[0]
                    age_str = parts[1]
                    return (gender_prefix, int(age_str))
            except ValueError:
                pass
            if col.startswith('f_'):
                return ('f', col)
            elif col.startswith('m_'):
                return ('m', col)
            else:
                return ('other', col)
        sorted_new_cols = sorted(new_cols, key=sort_key)

        # Define final column order
        fixed_cols = ['Country', 'Year', 'x', 'y', 'TotalPopulation']
        all_present_cols = df.columns.tolist()
        final_cols = [col for col in fixed_cols if col in all_present_cols] + [col for col in sorted_new_cols if col in all_present_cols]
        existing_other_cols = [col for col in all_present_cols if col not in final_cols]
        final_cols.extend(existing_other_cols)

        # Reindex the DataFrame to the final column order
        df = df[final_cols]

        # --- Save updated CSV using pandas' efficient method ---
        report_status("Saving updated CSV...")
        try:
            df.to_csv(output_csv_path, index=False, encoding='utf-8')
        except Exception as e:
            report_error(f"Error saving output CSV file:\n{e}")
            return

        # Clean up final pandas DataFrame to save memory
        del df

        report_completion(output_csv_path, skipped_files) # Signal success

    except Exception as e:
        # Catch any unexpected errors during the main flow of the task setup or intermediate steps
        report_error(f"An unexpected error occurred during processing task: {str(e)}")


# --- GUI Application Class ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Consolidate TIFF Data to CSV")
        self.geometry("600x400") # Give it a reasonable initial size

        self.initial_csv_path = None
        self.initial_tif_path = None
        self.tif_folder = None
        self.output_csv_path = None
        self.processing_thread = None

        self.create_widgets()
        self.check_queue() # Start checking the message queue periodically

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(expand=True, fill="both")

        # Configure grid for the frame
        main_frame.columnconfigure(1, weight=1) # Path labels column expands
        # Adjust row weights - removed progress row
        for i in range(7): # Rows for selectors (0-3), separator (4), button (5), status (6)
            main_frame.rowconfigure(i, weight=0)

        # Input CSV Selection (Step 2 Output)
        ttk.Label(main_frame, text="Input CSV (Step 2):").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        self.initial_csv_label = ttk.Label(main_frame, text="No file selected", foreground="gray")
        self.initial_csv_label.grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_initial_csv).grid(row=0, column=2, sticky="e", pady=2, padx=5)

        # Input Base TIFF Selection (for geotransform, typically TotalPopulation)
        ttk.Label(main_frame, text="Base TIFF (for Geo):").grid(row=1, column=0, sticky="w", pady=2, padx=5)
        self.initial_tif_label = ttk.Label(main_frame, text="No file selected", foreground="gray")
        self.initial_tif_label.grid(row=1, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_initial_tif).grid(row=1, column=2, sticky="e", pady=2, padx=5)

        # Input TIFF Folder Selection (Gender/Age TIFFs)
        ttk.Label(main_frame, text="TIFFs Folder:").grid(row=2, column=0, sticky="w", pady=2, padx=5)
        self.tif_folder_label = ttk.Label(main_frame, text="No folder selected", foreground="gray")
        self.tif_folder_label.grid(row=2, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_tif_folder).grid(row=2, column=2, sticky="e", pady=2, padx=5)

        # Output CSV File Selection
        ttk.Label(main_frame, text="Output CSV:").grid(row=3, column=0, sticky="w", pady=2, padx=5)
        self.output_csv_label = ttk.Label(main_frame, text="No path selected", foreground="gray")
        self.output_csv_label.grid(row=3, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_output_csv).grid(row=3, column=2, sticky="e", pady=2, padx=5)

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(row=4, column=0, columnspan=3, sticky="ew", pady=10)

        # Process Button
        self.process_button = ttk.Button(main_frame, text="Start Processing", command=self.start_processing)
        self.process_button.grid(row=5, column=0, columnspan=3, pady=10)

        # Status Label (Progress bar removed)
        self.status_label = ttk.Label(main_frame, text="Ready.")
        self.status_label.grid(row=6, column=0, columnspan=3, sticky="w", pady=5, padx=5) # Adjusted row index

    def select_initial_csv(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select Initial CSV File created in step2",
            filetypes=[("CSV files", "*.csv")]
        )
        if file_path:
            self.initial_csv_path = file_path
            self.initial_csv_label.config(text=os.path.basename(file_path), foreground="black")
            self.suggest_output_csv()


    def select_initial_tif(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select TotalPopulation TIFF File (for GeoTransform)",
            filetypes=[("TIFF files", "*.tif *.tiff")]
        )
        if file_path:
            self.initial_tif_path = file_path
            self.initial_tif_label.config(text=os.path.basename(file_path), foreground="black")
            self.suggest_output_csv()


    def select_tif_folder(self):
        folder_path = filedialog.askdirectory(
            parent=self,
            title="Select Folder Containing Gender/Age TIFFs"
        )
        if folder_path:
            self.tif_folder = folder_path
            self.tif_folder_label.config(text=os.path.basename(folder_path), foreground="black")
            self.suggest_output_csv()

    def suggest_output_csv(self):
         # Suggest output path if Initial TIF and TIFF Folder are selected, and output isn't already chosen
         if (self.initial_tif_path or self.tif_folder) and (not self.output_csv_path or self.output_csv_label.cget("foreground") == "gray"):
             default_name = 'output.csv'
             initial_dir = os.path.expanduser("~")
             try:
                  # Prioritize getting name from first TIFF in the folder
                  if self.tif_folder and os.path.isdir(self.tif_folder):
                       tif_files_in_folder = [f for f in os.listdir(self.tif_folder) if f.lower().endswith(('.tif', '.tiff'))]
                       if tif_files_in_folder:
                            first_tif_name = tif_files_in_folder[0].rsplit('.', 1)[0].strip()
                            country, _, _, year, suffix = parse_tif_name(first_tif_name)
                            default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
                            initial_dir = self.tif_folder
                       elif self.initial_tif_path and os.path.exists(self.initial_tif_path): # Fallback to initial tif name if folder empty/no tif
                             initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                             country, _, _, year, suffix = parse_tif_name(initial_tif_name)
                             default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
                             initial_dir = os.path.dirname(self.initial_tif_path) # Suggest near initial tif

                  elif self.initial_tif_path and os.path.exists(self.initial_tif_path): # Just initial tif selected
                        initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                        country, _, _, year, suffix = parse_tif_name(initial_tif_name)
                        default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
                        initial_dir = os.path.dirname(self.initial_tif_path) # Suggest near initial tif


                  # Construct the suggested path only if we managed to get a better default name or dir
                  if default_name != 'output.csv' or initial_dir != os.path.expanduser("~"):
                       default_output_path = os.path.join(initial_dir, default_name)
                       self.output_csv_path = default_output_path
                       self.output_csv_label.config(text=os.path.basename(default_output_path), foreground="black")

             except ValueError:
                  pass # If parsing fails, just don't suggest automatically
             except Exception:
                  pass # Handle other potential errors

    def select_output_csv(self):
        default_name = 'output.csv'
        initial_dir = os.path.expanduser("~")

        # Try to get a sensible default name and directory based on currently selected inputs
        if self.tif_folder and os.path.isdir(self.tif_folder):
             initial_dir = self.tif_folder
             try:
                  tif_files_in_folder = [f for f in os.listdir(self.tif_folder) if f.lower().endswith(('.tif', '.tiff'))]
                  if tif_files_in_folder:
                       first_tif_name = tif_files_in_folder[0].rsplit('.', 1)[0].strip()
                       country, _, _, year, suffix = parse_tif_name(first_tif_name)
                       default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
                  elif self.initial_tif_path and os.path.exists(self.initial_tif_path): # Fallback to initial tif name
                        initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                        country, _, _, year, suffix = parse_tif_name(initial_tif_name)
                        default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
                        initial_dir = os.path.dirname(self.initial_tif_path) # Suggest near initial tif
             except ValueError:
                  pass
             except Exception:
                  pass

        elif self.initial_tif_path and os.path.exists(self.initial_tif_path): # Only initial tif selected
             initial_dir = os.path.dirname(self.initial_tif_path)
             try:
                  initial_tif_name = os.path.basename(self.initial_tif_path).rsplit('.', 1)[0].strip()
                  country, _, _, year, suffix = parse_tif_name(initial_tif_name)
                  default_name = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"
             except ValueError:
                  pass
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
        if not self.initial_csv_path or not os.path.exists(self.initial_csv_path):
            messagebox.showwarning("Warning", "Please select a valid Input CSV file.", parent=self)
            return
        if not self.initial_tif_path or not os.path.exists(self.initial_tif_path):
             messagebox.showwarning("Warning", "Please select a valid Base TIFF file (for GeoTransform).", parent=self)
             return
        if not self.tif_folder or not os.path.isdir(self.tif_folder):
            messagebox.showwarning("Warning", "Please select a valid TIFF folder.", parent=self)
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

        # Disable button and update status
        self.process_button.config(state="disabled")
        self.status_label.config(text="Processing started...")

        # Create and start the worker thread
        # Pass the required paths to the task function
        self.processing_thread = threading.Thread(target=process_tifs_task,
                                                args=(self.initial_csv_path,
                                                      self.initial_tif_path,
                                                      self.tif_folder,
                                                      self.output_csv_path))
        self.processing_thread.daemon = True # Allow main process to exit
        self.processing_thread.start()

    # --- Thread-Safe Communication via Queue ---
    def check_queue(self):
        """Check the message queue for updates from the worker thread."""
        try:
            while True:
                # Get a message from the queue without blocking
                message_type, data = message_queue.get_nowait()

                # Removed progress handling
                if message_type == "status":
                    status_text = data
                    self._do_update_status(status_text)
                elif message_type == "complete":
                    output_file_path, skipped_files = data
                    self._do_processing_complete(output_file_path, skipped_files)
                elif message_type == "error":
                    error_message = data
                    self._do_processing_error(error_message)

        except queue.Empty:
            # No messages in the queue, schedule the next check
            pass
        finally:
            # Schedule the next check regardless of whether messages were processed
            self.after(100, self.check_queue) # Check every 100 ms

    # --- Actual GUI Update Methods (called by check_queue in main thread) ---

    # Removed _do_update_progress

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
            # Progress bar update removed
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
            # Progress bar update removed
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
    gdal.SetConfigOption('CPL_REDIRECT_STDERR', 'NO')
    gdal.SetConfigOption('CPL_SUPRESS_GDAL_DATA_WARNING', 'YES')

    app = App()
    app.mainloop() # Start the main Tkinter event loop
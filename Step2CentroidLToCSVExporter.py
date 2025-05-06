import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from osgeo import gdal
import numpy as np
import csv
import threading # Import threading for running the task in the background

"""
This script converts raster pixel data to centroid coordinates and exports to CSV.
It uses a GUI panel with buttons, path displays, a progress bar, and runs processing in a background thread.
"""

# Function containing the core processing logic
# This will be run in a separate thread
def process_raster_task(input_file, output_file, progress_callback, completion_callback, error_callback):
    """
    Process the raster file and export to CSV.
    Reports progress and completion/error via callbacks.
    This function runs in a separate thread.
    """
    try:
        # Report initial status
        progress_callback(0, 100, f"Opening file: {os.path.basename(input_file)}")

        # Open the dataset
        ds = gdal.Open(input_file)
        if ds is None:
            error_callback(f"Unable to open file: {input_file}")
            return False # Indicate failure

        # Get the geotransform
        gt = ds.GetGeoTransform()
        if gt is None:
            ds = None # Release dataset resource
            error_callback("File does not contain Geo Transform Information")
            return False

        # Get the number of rows and columns
        rows = ds.RasterYSize
        cols = ds.RasterXSize

        # Get the first band
        band = ds.GetRasterBand(1)
        if band is None:
            ds = None # Release dataset resource
            error_callback("Unable to find band in file")
            return False

        # Get nodata value
        nodatavalue = band.GetNoDataValue()

        # Report reading status
        progress_callback(0, 100, "Reading raster data...")

        # Read the entire raster data at once
        data = band.ReadAsArray()

        # Release band and dataset resources early
        band = None
        ds = None

        # Report processing status
        progress_callback(0, 100, "Processing data...")

        # Create meshgrid for row and column indices
        col_indices, row_indices = np.meshgrid(np.arange(cols), np.arange(rows))

        # Mask out nodata values
        if nodatavalue is not None:
            # Ensure data type supports comparison if nodatavalue is float/int
            # Use a tolerance for floating point nodata values if necessary,
            # but simple equality check is often sufficient if nodata is an integer.
            valid_mask = (data != nodatavalue)
        else:
            valid_mask = np.ones_like(data, dtype=bool)

        # Get valid data points
        valid_rows = row_indices[valid_mask]
        valid_cols = col_indices[valid_mask]
        valid_values = data[valid_mask]

        # Calculate center coordinates using vectorized operations
        # Ensure calculations handle potential floating point correctly
        x_centers = gt[0] + (valid_cols.astype(float) + 0.5) * gt[1] + (valid_rows.astype(float) + 0.5) * gt[2]
        y_centers = gt[3] + (valid_cols.astype(float) + 0.5) * gt[4] + (valid_rows.astype(float) + 0.5) * gt[5]

        # Clean up intermediate numpy arrays to save memory
        del data, col_indices, row_indices, valid_mask
        # Keep valid_rows, valid_cols, valid_values, x_centers, y_centers for writing

        num_records = len(valid_values)
        # Report writing status
        progress_callback(0, num_records, f"Writing {num_records} records to CSV...")

        # Write to CSV
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['x', 'y', 'TotalPopulation'])
                # Iterate and write, updating progress
                # Iterate over indices for progress tracking
                for i in range(num_records):
                    writer.writerow([x_centers[i], y_centers[i], valid_values[i]])
                    # Update progress less frequently for performance
                    if (i + 1) % 5000 == 0: # Update every 5000 rows, adjust as needed
                         progress_callback(i + 1, num_records, f"Writing record {i + 1}/{num_records}...")

            # Ensure progress bar reaches 100% at the end if loop didn't hit the last update point
            progress_callback(num_records, num_records, "Writing complete.")

        except Exception as e:
            # Handle potential errors during writing
            error_callback(f"Error happened while writing CSV: {str(e)}")
            return False # Indicate failure

        # Clean up final numpy arrays
        del valid_values, x_centers, y_centers, valid_rows, valid_cols

        completion_callback(output_file) # Signal success and pass the output file path
        return True # Indicate success

    except Exception as e:
        # Catch any unexpected errors during processing setup or numpy operations
        error_callback(f"An unexpected error occurred during processing: {str(e)}")
        return False # Indicate failure


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Raster Centroid to CSV Exporter")
        # self.geometry("450x300") # Optional initial size

        self.input_file_path = None
        self.output_file_path = None
        self.processing_thread = None # To keep track of the worker thread

        self.create_widgets()

        # Ensure the application quits cleanly when the window is closed
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        # Use a frame to hold everything for better organization and padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(expand=True, fill="both")

        # Configure grid weights for better resizing
        main_frame.columnconfigure(1, weight=1) # Allow the path label column to expand

        # Input File Selection
        ttk.Label(main_frame, text="Input TIFF File:").grid(row=0, column=0, sticky="w", pady=5, padx=5)
        self.input_path_label = ttk.Label(main_frame, text="No file selected", foreground="gray")
        self.input_path_label.grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_input).grid(row=0, column=2, sticky="e", pady=5, padx=5)

        # Output File Selection
        ttk.Label(main_frame, text="Output CSV File:").grid(row=1, column=0, sticky="w", pady=5, padx=5)
        self.output_path_label = ttk.Label(main_frame, text="No path selected", foreground="gray")
        self.output_path_label.grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.select_output).grid(row=1, column=2, sticky="e", pady=5, padx=5)

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)

        # Process Button
        self.process_button = ttk.Button(main_frame, text="Start Processing", command=self.start_processing)
        # Span across all columns
        self.process_button.grid(row=3, column=0, columnspan=3, pady=10)

        # Progress Bar
        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=5, padx=5)

        # Status Label
        self.status_label = ttk.Label(main_frame, text="Ready.")
        self.status_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=5, padx=5)

        # Adjust window size based on widgets
        self.update_idletasks()
        self.geometry(self.winfo_geometry()) # Set size to fit widgets
        self.minsize(self.winfo_width(), self.winfo_height()) # Prevent shrinking too much

    def select_input(self):
        file_path = filedialog.askopenfilename(
            parent=self, # Parent the dialog to the main window
            title="Please Select Tif file",
            filetypes=[("TIFF files", "*.tif *.tiff")]
        )
        if file_path:
            self.input_file_path = file_path
            self.input_path_label.config(text=os.path.basename(file_path), foreground="black")
            # Suggest a default output path based on the input file if output is not set
            if not self.output_file_path or self.output_path_label.cget("foreground") == "gray":
                 base_name = os.path.basename(file_path).rsplit('.', 1)[0] + '.csv'
                 # Suggest path in the same directory as the input
                 default_output_path = os.path.join(os.path.dirname(file_path), base_name)
                 self.output_file_path = default_output_path
                 self.output_path_label.config(text=os.path.basename(default_output_path), foreground="black")


    def select_output(self):
        default_name = 'output.csv'
        initial_dir = os.path.expanduser("~") # Start in user's home directory
        if self.input_file_path:
             # If input file is selected, suggest name based on input and start in input directory
             default_name = os.path.basename(self.input_file_path).rsplit('.', 1)[0] + '.csv'
             initial_dir = os.path.dirname(self.input_file_path)

        file_path = filedialog.asksaveasfilename(
            parent=self, # Parent the dialog to the main window
            title="Please Select File Save Path",
            defaultextension=".csv",
            initialfile=default_name,
            initialdir=initial_dir, # Set initial directory for the dialog
            filetypes=[("CSV files", "*.csv")]
        )
        if file_path:
            self.output_file_path = file_path
            self.output_path_label.config(text=os.path.basename(file_path), foreground="black")

    def start_processing(self):
        # Basic validation
        if not self.input_file_path or not os.path.exists(self.input_file_path):
            messagebox.showwarning("Warning", "Please select a valid input TIFF file.", parent=self)
            return
        if not self.output_file_path:
            # If output isn't set but input is, suggest the default again
            if self.input_file_path and self.output_path_label.cget("foreground") == "black":
                 # The path was set automatically based on input, user didn't browse
                 # We can just proceed if the path is valid
                 pass # Proceed to directory check
            else:
                 messagebox.showwarning("Warning", "Please select an output CSV file path.", parent=self)
                 return

        # Ensure the output directory exists
        output_dir = os.path.dirname(self.output_file_path)
        if output_dir and not os.path.exists(output_dir):
             try:
                  os.makedirs(output_dir)
             except OSError as e:
                  messagebox.showerror("Error", f"Could not create output directory {output_dir}:\n{e}", parent=self)
                  return

        # Prevent starting multiple processes
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showinfo("Info", "Processing is already running.", parent=self)
            return

        # Disable the process button to prevent re-clicks
        self.process_button.config(state="disabled")
        self.progress.config(mode="determinate", value=0) # Reset progress bar
        self.status_label.config(text="Processing started...")

        # Create and start the worker thread
        self.processing_thread = threading.Thread(target=process_raster_task,
                                                args=(self.input_file_path,
                                                      self.output_file_path,
                                                      self.update_progress,        # Pass progress callback
                                                      self.processing_complete,      # Pass completion callback
                                                      self.processing_error))      # Pass error callback
        self.processing_thread.daemon = True # Allow the main program to exit even if thread is running
        self.processing_thread.start()

    # --- Callbacks for thread to communicate with the main GUI thread ---

    def update_progress(self, value, max_value, status_text):
        """Called by the worker thread to request a GUI update."""
        # Schedule the actual update function to run in the main GUI thread
        self.after(0, self._do_update_progress, value, max_value, status_text)

    def _do_update_progress(self, value, max_value, status_text):
        """Performs the actual GUI update in the main thread."""
        try:
            # Check if widgets still exist before updating
            if self.progress.winfo_exists():
                self.progress.config(maximum=max_value, value=value)
            if self.status_label.winfo_exists():
                self.status_label.config(text=status_text)
        except tk.TclError:
            # Ignore errors if the widget is destroyed during update
            pass

    def processing_complete(self, output_file_path):
        """Called by the worker thread upon successful completion."""
        # Schedule the completion actions to run in the main GUI thread
        self.after(0, self._do_processing_complete, output_file_path)

    def _do_processing_complete(self, output_file_path):
        """Performs final actions in the main thread after success."""
        try:
            if self.status_label.winfo_exists():
                 self.status_label.config(text="Processing complete.")
            if self.process_button.winfo_exists():
                 self.process_button.config(state="normal") # Re-enable the button
            # Show success message
            messagebox.showinfo("Success", f"CSV file successfully created:\n{output_file_path}", parent=self)
        except tk.TclError:
            pass


    def processing_error(self, error_message):
        """Called by the worker thread upon error."""
        # Schedule the error actions to run in the main GUI thread
        self.after(0, self._do_processing_error, error_message)

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
        # Check if a thread is running before closing
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askyesno("Quit", "Processing is still running. Are you sure you want to quit?", parent=self):
                # If user confirms, the daemon thread will be terminated when the main program exits
                self.destroy() # Destroy the main window
        else:
            self.destroy() # Destroy the main window


# Main execution block
if __name__ == "__main__":
    app = App()
    app.mainloop() # Start the main Tkinter event loop
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from osgeo import gdal
import numpy as np
import csv

"""
This script converts raster pixel data to centroid coordinates and exports to CSV.
It uses a GUI for file selection and optimizes performance with NumPy.
"""

def select_input_file():
    """Open a file dialog to select the input TIFF file."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    file_path = filedialog.askopenfilename(
        title="Please Select Tif file",
        filetypes=[("TIFF files", "*.tif *.tiff")]
    )
    root.destroy()
    return file_path

def select_output_path(default_name):
    """Open a file dialog to select the output CSV file path."""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.asksaveasfilename(
        title="Please Select File Save Path",
        defaultextension=".csv",
        initialfile=default_name,
        filetypes=[("CSV files", "*.csv")]
    )
    root.destroy()
    return file_path

def process_raster_to_csv(input_file, output_file):
    """Process the raster file and export to CSV with optimized performance."""
    # Open the dataset
    ds = gdal.Open(input_file)
    if ds is None:
        messagebox.showerror("Error", f"Unable to open file: {input_file}")
        sys.exit(1)

    # Get the geotransform
    gt = ds.GetGeoTransform()
    if gt is None:
        messagebox.showerror("Error", "File does not contain Geo Transform Information")
        sys.exit(1)

    # Get the number of rows and columns
    rows = ds.RasterYSize
    cols = ds.RasterXSize

    # Get the first band
    band = ds.GetRasterBand(1)
    if band is None:
        messagebox.showerror("Error", "Unable to find band in file")
        sys.exit(1)

    # Get nodata value
    nodatavalue = band.GetNoDataValue()

    # Read the entire raster data at once
    data = band.ReadAsArray()

    # Create meshgrid for row and column indices
    col_indices, row_indices = np.meshgrid(np.arange(cols), np.arange(rows))

    # Mask out nodata values
    if nodatavalue is not None:
        valid_mask = data != nodatavalue
    else:
        valid_mask = np.ones_like(data, dtype=bool)

    # Get valid data points
    valid_rows = row_indices[valid_mask]
    valid_cols = col_indices[valid_mask]
    valid_values = data[valid_mask]

    # Calculate center coordinates using vectorized operations
    x_centers = gt[0] + (valid_cols + 0.5) * gt[1] + (valid_rows + 0.5) * gt[2]
    y_centers = gt[3] + (valid_cols + 0.5) * gt[4] + (valid_rows + 0.5) * gt[5]

    # Write to CSV
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['x', 'y', 'TotalPopulation'])
        for x, y, value in zip(x_centers, y_centers, valid_values):
            writer.writerow([x, y, value])

    return True

def main():
    """Main function to run the script with GUI."""
    # Select input file
    input_file = select_input_file()
    if not input_file:
        messagebox.showinfo("Attention", "No file selected, program end.")
        sys.exit(0)

    # Determine default output file name
    base_name = os.path.basename(input_file).rsplit('.', 1)[0] + '.csv'

    # Select output file path
    output_file = select_output_path(base_name)
    if not output_file:
        messagebox.showinfo("Attention", "No save path selected, program end.")
        sys.exit(0)

    # Process the raster and create CSV
    try:
        success = process_raster_to_csv(input_file, output_file)
        if success:
            messagebox.showinfo("Succed", f"CSV file succseful created: {output_file}")
    except Exception as e:
        messagebox.showerror("Error", f"Error happened while processing: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
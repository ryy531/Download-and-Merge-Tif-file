import os
import sys
from osgeo import gdal
import pandas as pd
import numpy as np
from tkinter import Tk, filedialog

def parse_tif_name(tif_name):
    """
    Parse TIFF file name into components: country, gender, age, year, suffix.
    
    Parameters:
    tif_name (str): The base name of the TIFF file without extension.
    
    Returns:
    tuple: (country, gender, age, year, suffix)
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
    tuple: The pixel indices (col, row).
    """
    scalex = gt[1]
    scaley = gt[5]
    ulx = gt[0]
    uly = gt[3]
    
    col = int((x - ulx) / scalex)
    
    if scaley < 0:
        row = int((y - uly) / scaley)
    else:
        row = int((uly - y) / scaley)
    
    return col, row

def main():
    # Create and hide the root window for file dialogs
    root = Tk()
    root.withdraw()

    # Open dialog for selecting initial CSV file
    initial_csv_path = filedialog.askopenfilename(title="Select Initial CSV File created in step2", filetypes=[("CSV files", "*.csv")])
    if not initial_csv_path:
        print("No CSV file selected. Exiting.")
        root.destroy()
        sys.exit(1)

    # Open dialog for selecting initial TIFF file for geotransform
    initial_tif_path = filedialog.askopenfilename(title="Select TotalPopulation TIFF File", filetypes=[("TIFF files", "*.tif *.tiff")])
    if not initial_tif_path:
        print("No initial TIFF file selected. Exiting.")
        root.destroy()
        sys.exit(1)

    # Open dialog for selecting TIFF folder
    tif_folder = filedialog.askdirectory(title="Select TIFF Folder")
    if not tif_folder:
        print("No TIFF folder selected. Exiting.")
        root.destroy()
        sys.exit(1)

    # Get list of tif files in the folder
    tif_files = [file for file in os.listdir(tif_folder) if file.endswith('.tif')]
    tif_paths = [os.path.join(tif_folder, file) for file in tif_files]
    if len(tif_paths) == 0:
        print("No TIFF files found in the selected folder.")
        root.destroy()
        sys.exit(1)

    # Parse the first TIFF file to determine output CSV file name
    first_tif_path = tif_paths[0]
    first_tif_name = os.path.basename(first_tif_path).rsplit('.', 1)[0].strip()
    try:
        country, _, _, year, suffix = parse_tif_name(first_tif_name)
    except ValueError as e:
        print(f"Error parsing first TIFF file name: {e}")
        root.destroy()
        sys.exit(1)

    # Set initial file name for output CSV
    initialfile = f"{country}_{year}_{suffix}.csv" if suffix else f"{country}_{year}.csv"

    # Open dialog for saving output CSV file
    output_csv_path = filedialog.asksaveasfilename(title="Save Output CSV As", initialdir=tif_folder, initialfile=initialfile, defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if not output_csv_path:
        print("No output path selected. Exiting.")
        root.destroy()
        sys.exit(1)

    # Destroy the root window after getting all paths
    root.destroy()

    # Read initial CSV
    df = pd.read_csv(initial_csv_path)

    # Check required columns in initial CSV
    required_initial_cols = ['x', 'y', 'TotalPopulation']
    for col in required_initial_cols:
        if col not in df.columns:
            print(f"Error: Column {col} not found in initial CSV")
            sys.exit(1)

    # Get geotransform of initial tif file
    initial_ds = gdal.Open(initial_tif_path)
    if initial_ds is None:
        print("Error opening initial tif file:", initial_tif_path)
        sys.exit(1)
    gt_initial = initial_ds.GetGeoTransform()
    if gt_initial is None:
        print("Error: Initial tif file does not contain georeferencing information.")
        sys.exit(1)
    initial_ds = None  # Close to free resources

    # Calculate col and row for each row in df
    df['col'], df['row'] = zip(*df.apply(lambda row: xy_to_pixel(row['x'], row['y'], gt_initial), axis=1))

    # Process each tif file individually
    for tif_path in tif_paths:
        ds = gdal.Open(tif_path)
        if ds is None:
            print("Error opening tif file:", tif_path)
            continue
        gt = ds.GetGeoTransform()
        if gt != gt_initial:
            print(f"Warning: {tif_path} geotransform does not match, but processing anyway.")
        rows_tif = ds.RasterYSize
        cols_tif = ds.RasterXSize
        band = ds.GetRasterBand(1)
        if band is None:
            print("Error: No band found in", tif_path)
            continue
        try:
            nodatavalue = band.GetNoDataValue()
        except:
            nodatavalue = None
        array = band.ReadAsArray()
        
        # Parse TIFF file name to get column name
        tif_name_full = os.path.basename(tif_path).rsplit('.', 1)[0].strip()
        try:
            _, gender, age, _, _ = parse_tif_name(tif_name_full)
        except ValueError as e:
            print(f"Warning: Skipping {tif_name_full} due to parsing error: {e}")
            continue
        col_name = f"{gender}_{age}"

        # Extract values using vectorized operations
        cols = df['col'].values
        rows = df['row'].values
        values = np.full(len(df), None)
        mask = (rows >= 0) & (rows < array.shape[0]) & (cols >= 0) & (cols < array.shape[1])
        if mask.any():
            values[mask] = array[rows[mask].astype(int), cols[mask].astype(int)]
            if nodatavalue is not None:
                values[mask] = np.where(values[mask] != nodatavalue, values[mask], None)
        else:
            values = np.full(len(df), None)
        df[col_name] = values

        ds = None  # Close dataset to free resources

    # Add Country and Year columns
    df['Country'] = country
    df['Year'] = year

    # Drop temporary columns
    df = df.drop(['row', 'col'], axis=1)

    # Sort new columns (f_* and m_*)
    new_cols = [col for col in df.columns if col.startswith(('f_', 'm_'))]
    def sort_key(col):
        if col.startswith('f_'):
            return ('f', int(col[2:]))
        elif col.startswith('m_'):
            return ('m', int(col[2:]))
        else:
            return (col, 0)
    sorted_new_cols = sorted(new_cols, key=sort_key)

    # Define final column order
    fixed_cols = ['Country', 'Year', 'x', 'y', 'TotalPopulation']
    all_cols = fixed_cols + sorted_new_cols
    df = df[all_cols]

    # Save updated CSV
    df.to_csv(output_csv_path, index=False)
    print("Updated CSV file saved:", output_csv_path)

if __name__ == '__main__':
    main()
import os
import sys
from osgeo import gdal
import pandas as pd
import numpy as np

"""
this is the file that could deal with multiple tif files. 
"""

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
    # User input
    initial_csv_path = input("Please enter the path to the initial CSV file: ")
    tif_folder = input("Please enter the path to the folder containing multiple tif files: ")
    output_csv_path = input("Please enter the path to save the updated CSV file: ")
    initial_tif_path = input("Please enter the path to the initial tif file: ")

    # Read initial CSV
    df = pd.read_csv(initial_csv_path)

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

    # Get list of tif files in the folder
    tif_files = [file for file in os.listdir(tif_folder) if file.endswith('.tif')]
    tif_paths = [os.path.join(tif_folder, file) for file in tif_files]

    # Process each tif file individually to ensure no data is skipped
    for tif_path in tif_paths:
        ds = gdal.Open(tif_path)
        if ds is None:
            print("Error opening tif file:", tif_path)
            continue
        gt = ds.GetGeoTransform()
        if gt != gt_initial:
            print(f"Warning: {tif_path} geotransform does not match, but processing anyway as per user request.")
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
        tif_name = os.path.basename(tif_path).rsplit('.', 1)[0]

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
            values = np.full(len(df), None)  # Ensure all positions are processed, even if out of bounds
        df[tif_name] = values

        ds = None  # Close dataset to free resources

    # Save updated CSV
    df.to_csv(output_csv_path, index=False)
    print("Updated CSV file saved:", output_csv_path)

if __name__ == '__main__':
    main()
import os
import sys
from osgeo import gdal
import pandas as pd
'''
This file only for deal with single tif file, just for testing
'''
def xy_to_pixel(x, y, gt):
    """
    Convert map coordinates (x,y) to pixel indices (c,r) using the geotransform.
    
    Parameters:
    x (float): The x-coordinate.
    y (float): The y-coordinate.
    gt (tuple): The geotransform of the raster.
    
    Returns:
    tuple: The pixel indices (c,r).
    """
    scalex = gt[1]
    scaley = gt[5]
    ulx = gt[0]
    uly = gt[3]
    
    c = int((x - ulx) / scalex)
    
    # Handle row index based on whether scaley is negative or positive
    if scaley < 0:
        r = int((y - uly) / scaley)
    else:
        r = int((uly - y) / scaley)
    
    return c, r

def main():
    # Prompt user for input paths
    original_csv_path = input("Please enter the path to the original CSV file: ")
    new_tif_path = input("Please enter the path to the new tif file: ")
    output_csv_path = input("Please enter the path to save the updated CSV file: ")

    # Read original CSV file
    df = pd.read_csv(original_csv_path)

    # Open new tif file
    new_ds = gdal.Open(new_tif_path)
    if new_ds is None:
        print("Error opening new tif file:", new_tif_path)
        sys.exit(1)

    # Get geotransform
    new_gt = new_ds.GetGeoTransform()
    if new_gt is None:
        print("Error: New tif file does not contain georeferencing information.")
        sys.exit(1)

    # Get band
    new_band = new_ds.GetRasterBand(1)
    if new_band is None:
        print("Error: No band found in the new tif file.")
        sys.exit(1)

    # Get nodata value
    try:
        new_nodatavalue = new_band.GetNoDataValue()
    except:
        new_nodatavalue = None

    # Initialize list to hold new values
    new_values = []

    # Iterate through each row in the CSV
    for index, row in df.iterrows():
        x = row['x']
        y = row['y']

        # Convert x,y to pixel coordinates in new tif file
        c, r = xy_to_pixel(x, y, new_gt)

        # Check if within bounds
        cols = new_ds.RasterXSize
        rows = new_ds.RasterYSize
        if c < 0 or c >= cols or r < 0 or r >= rows:
            new_values.append(None)  # or some special value
        else:
            # Read value from new tif file
            value = new_band.ReadAsArray(c, r, 1, 1)[0][0]
            if new_nodatavalue is not None and value == new_nodatavalue:
                new_values.append(None)
            else:
                new_values.append(value)

    # Determine column name based on new tif file name
    column_name = os.path.basename(new_tif_path).rsplit('.', 1)[0]

    # Add new column to dataframe
    df[column_name] = new_values

    # Save updated CSV
    df.to_csv(output_csv_path, index=False)
    print("Updated CSV file saved:", output_csv_path)

if __name__ == '__main__':
    main()
# WorldPop Data Processing Tool

A desktop tool that turns WorldPop population rasters into an analysis-ready table. It downloads a full set of GeoTIFFs, converts every populated pixel into a point with coordinates, and joins 36 age-and-sex rasters onto those points, so one CSV holds total population plus a full age-sex breakdown for every location.

I built it to prepare the population data behind my [Education Atlas web GIS platform](https://github.com/ryy531/GeoServer_GIS_Analytics_Platform), where the output powers the 5 km buffer analysis and the population pyramid dashboard.

## The problem it solves

WorldPop publishes population as many separate rasters: one for total population and one for each sex and 5-year age group (for example `pak_f_0_2020`, `pak_m_45_2020`). Getting them into a database by hand means downloading dozens of files, converting each raster, and lining up the values pixel by pixel. This tool does all of that in four guided steps with no command-line work.

## Workflow

The main window (`WorldPopTool.py`) is a launcher with one button per step. Each step opens its own window with file pickers, a progress bar and status messages.

| Step | Script | What it does |
|---|---|---|
| 1. Download | `Step1Downloader.py` | Reads a WorldPop data page, finds every `.tif` link, and downloads them all into a folder you choose |
| 2. Raster to points | `Step2CentroidLToCSVExporter.py` | Converts each valid pixel of a raster into its centroid coordinates and value, skipping NoData cells, and writes a CSV |
| 3. Join age-sex rasters | `Step3ProcessMultipleTifs.py` | Samples every age-sex raster at those points and adds one column per raster (`f_0`, `f_1`, `f_5` … `m_80`), using the file name to build the column name |
| 4. Combine age groups | `Step4CombineAgeGroup.py` | Adds summary columns for any age range you enter, for each sex (for example `f_15_to_65_sum`) |

`MergedRasterToCSVExporter.py` runs steps 2 and 3 in a single pass.

## Output

One CSV row per populated pixel:

| Country | Year | x | y | TotalPopulation | f_0 | f_1 | … | m_80 | f_15_to_65_sum |
|---|---|---|---|---|---|---|---|---|---|

The table loads straight into PostGIS as a point layer.

## Technical details

- **GDAL** reads the rasters, applies the geotransform to convert between pixel and map coordinates, and handles NoData values.
- **NumPy** masks invalid cells across the whole array instead of looping over pixels.
- **Threading and a message queue** keep the Tkinter windows responsive while large rasters are processed.
- **Requests and BeautifulSoup** find and download the files.
- **Packaging support:** the launcher detects when it runs as a PyInstaller executable and sets `GDAL_DATA` so it works on machines without Python.
- **Logging** to `worldpoptool.log` for troubleshooting.

## Tech stack

Python, GDAL, NumPy, pandas, Tkinter, Requests, BeautifulSoup, PyInstaller

## Running it

Requirements: Python 3.9+ and GDAL. On Windows, the easiest way to get GDAL is through conda or OSGeo4W.

```bash
pip install numpy pandas requests beautifulsoup4
python WorldPopTool.py
```

Then run the steps in order from the launcher.

## Data source

Population data: [WorldPop](https://www.worldpop.org), licensed under CC BY 4.0.

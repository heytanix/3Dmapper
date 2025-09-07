# OSM 3D Map Exporter

A web-based tool to generate 3D building models from OpenStreetMap (OSM) data, optimized for simulation projects. Select an area on the map, and export the buildings as a `.obj` file.

 <!-- It's recommended to add a screenshot of your application -->

## Features

-   **Interactive Map Selection**: Use a Leaflet map to draw a bounding box over your desired area.
-   **Manual Coordinate Entry**: Precisely define your area by entering latitude and longitude coordinates.
-   **Customizable Export**:
    -   Set a default height for buildings without height data in OSM.
    -   Choose from different quality levels (Low, Medium, High) to control model detail and file size.
-   **Real-time Feedback**: See the selected coordinates, estimated area size, and status updates directly in the UI.
-   **Optimized Geometry**: The backend processes OSM data to create clean, lightweight `.obj` files suitable for simulations.

## How It Works

1.  **Frontend**: The user selects an area using the tools provided in the [templates/index.html](templates/index.html) file.
2.  **API Request**: A `POST` request is sent to the `/export_obj` endpoint on the Flask server with the bounding box, desired height, and quality settings.
3.  **Data Fetching**: The Flask backend, defined in [app.py](app.py), queries the Overpass API to get building footprint data for the selected area.
4.  **Geometry Processing**: The server processes the data:
    -   It converts geographic coordinates (lat/lon) to a local Cartesian coordinate system (in meters).
    -   Building footprints are simplified using the `shapely` library to reduce vertex count based on the selected quality.
    -   Building heights are determined from OSM tags (e.g., `building:height`, `building:levels`) or the user-provided default.
5.  **OBJ Generation**: The processed data is used to generate the vertices and faces for each building in the Wavefront OBJ format.
6.  **File Download**: The generated `.obj` file is sent back to the user for download.

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd 3Dmapper
    ```

2.  **Create a virtual environment and activate it:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install the required Python packages:**
    The project uses `requests`, `numpy`, and `shapely` in addition to `flask`. Update your `req.txt` to include all necessary packages.
    ```bash
    pip install -r req.txt
    ```

## How to Run

1.  **Start the Flask application:**
    ```bash
    python app.py
    ```

2.  **Open your web browser** and navigate to:
    [http://127.0.0.1:5000](http://127.0.0.1:5000)

## File Structure

```
.
├── app.py          # The main Flask application logic
├── templates/
│   └── index.html  # Frontend HTML, CSS, and JavaScript
├── req.txt         # Python package requirements
└── README.md       # This file
```
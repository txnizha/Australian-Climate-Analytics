from flask import Flask, request, send_file
import sqlite3
import pandas as pd
import numpy as np
import os
import io

app = Flask(__name__)

# --- 1. DATABASE CONNECTION ---
def get_db_connection():
    # This automatically finds the folder where app.py is currently sitting
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # This joins that folder path with your database filename
    db_file = os.path.join(base_dir, 'Climate_Data.db')
    return sqlite3.connect(db_file)

# --- 2. DATA LOADING FUNCTIONS ---
def get_station_names():
    try:
        conn = get_db_connection()
        query = "SELECT site_id, name FROM weather_station" 
        df = pd.read_sql_query(query, conn)
        conn.close()
        df['site_id'] = df['site_id'].astype(str)
        return pd.Series(df['name'].values, index=df['site_id'].values).to_dict()
    except Exception:
        return {}

def get_station_summary():
    all_data = []
    states = ['VIC', 'NSW', 'QLD', 'WA', 'SA', 'TAS', 'NT']
    conn = get_db_connection()
    
    for state in states:
        try:
            # FIX: We explicitly cast Location to TEXT inside the SQL query
            query = f"""
            SELECT CAST(Location AS TEXT) as Station_ID, '{state}' as State,
            AVG(MaxTemp) as Avg_Temp, 
            MAX(MaxTemp) as Highest_Temp,
            SUM(Precipitation) as Total_Rainfall,
            SUM(CASE WHEN Precipitation > 0 THEN 1 ELSE 0 END) as Rain_Days
            FROM {state} 
            WHERE MaxTemp IS NOT NULL AND Location IS NOT NULL
            GROUP BY Location
            """
            df_state = pd.read_sql_query(query, conn)
            if not df_state.empty:
                all_data.append(df_state)
        except Exception as e:
            # This will show you exactly which table is failing in your terminal
            print(f"Error loading table {state}: {e}")
            continue 
    conn.close()
    
    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        # Ensure numeric columns are strictly numeric for matching
        final_df['Avg_Temp'] = pd.to_numeric(final_df['Avg_Temp']).round(1)
        final_df['Status'] = 'Active'
        
        # Link the readable names from your weather_station table
        name_map = get_station_names()
        final_df['Location_Name'] = final_df['Station_ID'].map(name_map).fillna(final_df['Station_ID'])
        final_df['Location_Name'] = final_df['Location_Name'].str.title().str.strip()
        return final_df
    return pd.DataFrame()

def get_station_history(station_id, state):
    try:
        conn = get_db_connection()
        query = f"""
        SELECT DMY as Date, MaxTemp FROM {state} 
        WHERE Location = '{station_id}' AND MaxTemp IS NOT NULL
        ORDER BY Date DESC LIMIT 50
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        df = df.sort_values('Date')
        return df
    except Exception:
        return pd.DataFrame()

# --- 3. HTML GENERATOR ---
def get_page_html(form_data):
    raw_page = form_data.get('page')
    current_page = raw_page[0] if isinstance(raw_page, list) else raw_page
    if current_page:
        current_page = str(current_page).strip().lower()
    else:
        current_page = 'home'

    # --- DEFINE CONTENT ---
    if current_page == 'home':
        content = """
        <section class="hero">
            <h1>Australian Climate Analytics</h1>
            <p>A modern decision support system for analyzing historical weather trends (1970–2020). Now covering all states and territories.</p>
        </section>
        <div class="main-container grid-container">
            <div class="card"><div class="card-header"><i data-lucide="search" class="card-icon"></i><h3>Station Explorer</h3></div><p>Access raw historical data by region.</p><a href="?page=data" class="btn-black">Explore Data</a></div>
            <div class="card"><div class="card-header"><i data-lucide="trending-up" class="card-icon"></i><h3>Temp Trends</h3></div><p>Compare temperature shifts over decades.</p><a href="?page=temps" class="btn-black">View Trends</a></div>
            <div class="card"><div class="card-header"><i data-lucide="cloud-rain" class="card-icon"></i><h3>Metric Viewer</h3></div><p>Deep dive into specific weather metrics.</p><a href="?page=metrics" class="btn-black">Analyze</a></div>
            <div class="card"><div class="card-header"><i data-lucide="link" class="card-icon"></i><h3>Similarity Check</h3></div><p>Find stations with matching patterns.</p><a href="?page=similarity" class="btn-black">Run Check</a></div>
            <div class="card"><div class="card-header"><i data-lucide="download" class="card-icon"></i><h3>Export Data</h3></div><p>Download generated reports.</p><a href="?page=export" class="btn-black">Download</a></div>
            <div class="card"><div class="card-header"><i data-lucide="users" class="card-icon"></i><h3>Our Team</h3></div><p>Meet the analysts and developers.</p><a href="?page=about" class="btn-black">Meet Team</a></div>
        </div>"""
    
    elif current_page == 'data':
        df = get_station_summary()
        table_rows = ""
        if not df.empty:
            for index, row in df.iterrows():
                table_rows += f"""
                <tr>
                    <td><strong>{row['Location_Name']}</strong> <span style="color:#9ca3af; font-size:0.8em;">({row['Station_ID']})</span></td>
                    <td>{row['State']}</td>
                    <td>{row['Avg_Temp']}°C</td>
                    <td>{int(row['Total_Rainfall'])}mm</td>
                    <td><span class="badge badge-green">{row['Status']}</span></td>
                    <td><a href="?page=temps&station={row['Station_ID']}&state={row['State']}" style="color:#ea580c; text-decoration:none;">View →</a></td>
                </tr>"""
        else:
            table_rows = "<tr><td colspan='6'>No data found.</td></tr>"
            
        content = f"""
        <section class="hero"><h1>Station Explorer</h1><p>Real-time data from all Australian States.</p></section>
        <div class="main-container">
            <div class="glass-panel" style="padding: 0; overflow: hidden;">
                <table><thead><tr><th>Station Name</th><th>State</th><th>Avg Max Temp</th><th>Total Rain</th><th>Status</th><th>Action</th></tr></thead><tbody>{table_rows}</tbody></table>
            </div>
        </div>"""
    
    elif current_page == 'temps':
        selected_station = form_data.get('station')
        selected_state = form_data.get('state')
        chart_script = ""
        chart_title = "Select a station to view history"
        
        if selected_station and selected_state:
            history_df = get_station_history(selected_station, selected_state)
            name_map = get_station_names()
            station_name = name_map.get(str(selected_station), selected_station).title()
            
            if not history_df.empty:
                chart_title = f"Temperature History: {station_name}"
                dates = history_df['Date'].tolist()
                temps = history_df['MaxTemp'].tolist()
                chart_script = f"""
                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <script>
                    const ctx = document.getElementById('trendChart').getContext('2d');
                    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
                    gradient.addColorStop(0, 'rgba(234, 88, 12, 0.4)');
                    gradient.addColorStop(1, 'rgba(234, 88, 12, 0.0)');

                    new Chart(ctx, {{
                        type: 'line',
                        data: {{
                            labels: {dates}, 
                            datasets: [{{
                                label: 'Max Temp (°C)', data: {temps},
                                borderColor: '#ea580c', backgroundColor: gradient,
                                pointBackgroundColor: '#fff', pointBorderColor: '#ea580c',
                                pointRadius: 4, pointHoverRadius: 6, borderWidth: 2, tension: 0.4, fill: true
                            }}]
                        }},
                        options: {{
                            responsive: true, maintainAspectRatio: false,
                            plugins: {{ legend: {{ display: false }} }},
                            scales: {{ 
                                x: {{ 
                                    grid: {{ display: false }}, 
                                    ticks: {{ 
                                        font: {{ family: "'Inter', sans-serif" }},
                                        maxRotation: 0, minRotation: 0, autoSkip: true, maxTicksLimit: 12
                                    }} 
                                }},
                                y: {{ grid: {{ color: 'rgba(0,0,0,0.05)', borderDash: [5, 5] }}, ticks: {{ font: {{ family: "'Inter', sans-serif" }} }} }} 
                            }}
                        }}
                    }});
                </script>"""
            else:
                chart_title = f"No Data Found for {station_name}"

        chart_area = '<canvas id="trendChart"></canvas>' if selected_station else """<div style="text-align: center; color: #9ca3af;"><i data-lucide="bar-chart-2" style="width: 64px; height: 64px; margin-bottom: 1rem;"></i><p>Please select a station from the <a href="?page=data" style="color:#ea580c;">Data Page</a></p></div>"""
        content = f"""
        <section class="hero"><h1>Temperature Trends</h1><p>{chart_title}</p></section>
        <div class="main-container"><div class="glass-panel" style="text-align: center; min-height: 400px; display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 2rem;">{chart_area}</div></div>
        {chart_script}"""
    
    elif current_page == 'metrics':
                selected_metric = form_data.get('metric', 'rain')
                df = get_station_summary()
                
                if not df.empty:
                    if selected_metric == 'temp':
                        df = df.sort_values('Avg_Temp', ascending=True)
                        chart_label, page_title = "Average Max Temp (°C)", "Top 10 Hottest Stations (Avg)"
                        data_values = df['Avg_Temp'].tolist()[-10:]
                    elif selected_metric == 'highest_temp':
                        df = df.sort_values('Highest_Temp', ascending=True)
                        chart_label, page_title = "Highest Recorded Temp (°C)", "Top 10 Extreme Heat Records"
                        data_values = df['Highest_Temp'].tolist()[-10:]
                    elif selected_metric == 'rain_days':
                        df = df.sort_values('Rain_Days', ascending=True)
                        chart_label, page_title = "Total Rainy Days (Count)", "Top 10 Most Frequent Rain"
                        data_values = df['Rain_Days'].tolist()[-10:]
                    else:
                        df = df.sort_values('Total_Rainfall', ascending=True) 
                        chart_label, page_title = "Total Rainfall (mm)", "Top 10 Wettest Stations (Volume)"
                        data_values = df['Total_Rainfall'].tolist()[-10:]
                    locations = df['Location_Name'].tolist()[-10:]
                else:
                    locations, data_values, chart_label, page_title = [], [], "No Data", "Metric Viewer"

                sel_rain = 'selected' if selected_metric == 'rain' else ''
                sel_temp = 'selected' if selected_metric == 'temp' else ''
                sel_high = 'selected' if selected_metric == 'highest_temp' else ''
                sel_days = 'selected' if selected_metric == 'rain_days' else ''

                content = f"""
                <section class="hero"><h1>Metric Viewer</h1><p>{page_title}</p></section>
                <div class="main-container" style="display: grid; grid-template-columns: 1fr 2fr; gap: 2rem; align-items: stretch;">
                    
                    <div class="glass-panel" style="padding: 3rem; display: flex; flex-direction: column; justify-content: center;">
                        <form action="/" method="get">
                            <input type="hidden" name="page" value="metrics">
                            <div class="form-group" style="margin-bottom: 2rem;">
                                <label style="font-weight: 600; margin-bottom: 1rem; display: block;">Select Metric</label>
                                <select name="metric" style="padding: 1rem; border-radius: 12px; width: 100%;">
                                    <option value="rain" {sel_rain}>Total Rainfall</option>
                                    <option value="rain_days" {sel_days}>Rainy Days</option>
                                    <option value="temp" {sel_temp}>Average Max Temp</option>
                                    <option value="highest_temp" {sel_high}>Highest Ever Temp</option>
                                </select>
                            </div>
                            <button type="submit" class="btn-black" style="width: 100%;">Update Chart</button>
                        </form>
                    </div>

                    <div class="glass-panel" style="padding: 2.5rem; min-height: 500px; display: flex; align-items: center;">
                        <canvas id="metricChart"></canvas>
                    </div>
                </div>

                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <script>
                    const ctx = document.getElementById('metricChart').getContext('2d');
                    new Chart(ctx, {{
                        type: 'bar',
                        data: {{
                            labels: {locations}, 
                            datasets: [{{
                                label: '{chart_label}', 
                                data: {data_values},
                                backgroundColor: '#ea580c', 
                                borderRadius: 8,
                                barThickness: 20,       // Sets the exact thickness
                                maxBarThickness: 25     // Prevents stretching on large screens
                            }}]
                        }},
                        options: {{
                            indexAxis: 'y', 
                            responsive: true, 
                            maintainAspectRatio: false,
                            plugins: {{ legend: {{ display: false }} }},
                            scales: {{
                                x: {{ grid: {{ display: true, color: 'rgba(0,0,0,0.05)' }} }},
                                y: {{ grid: {{ display: false }} }}
                            }}
                        }}
                    }});
                </script>
                """

    elif current_page == 'similarity':
        target_loc = form_data.get('target_loc', '').strip()
        result_html = ""
            
        if target_loc:
            conn = get_db_connection()
            name_map = get_station_names()
            states = ['VIC', 'NSW', 'QLD', 'WA', 'SA', 'TAS', 'NT']
            
            # IMPROVED: Try multiple ways to find the station
            target_id = None
            search_lower = target_loc.lower()
            
            # Method 1: Direct ID match
            if target_loc in name_map:
                target_id = target_loc
            
            # Method 2: Search by name (partial match)
            if not target_id:
                for sid, name in name_map.items():
                    if search_lower in name.lower():
                        target_id = sid
                        break
            
            # Method 3: Try using the input as-is (in case it's a valid ID not in weather_station)
            if not target_id:
                target_id = target_loc
            
            # Now search for temperature data
            target_data = None
            for state in states:
                try:
                    # Use parameterized query to avoid SQL injection
                    query = f"SELECT AVG(MaxTemp) as avg_temp FROM {state} WHERE CAST(Location AS TEXT) = ?"
                    res = pd.read_sql_query(query, conn, params=(str(target_id),))
                    if not res.empty and res.iloc[0]['avg_temp'] is not None:
                        # Get the display name
                        display_name = name_map.get(str(target_id), f"Station {target_id}")
                        target_data = {
                            'temp': res.iloc[0]['avg_temp'],
                            'name': display_name.title(),
                            'id': target_id,
                            'state': state
                        }
                        break
                except Exception as e:
                    print(f"Error searching {state}: {e}")
                    continue
                
            if target_data:
                # Find the closest match
                df = get_station_summary()
                df['diff'] = abs(df['Avg_Temp'] - target_data['temp'])
                # Filter out the target itself
                candidates = df[df['Station_ID'] != str(target_data['id'])].sort_values('diff')
                
                if not candidates.empty:
                    match = candidates.iloc[0]
                    
                    result_html = f"""
                    <div style="margin-top: 2.5rem; padding: 2.5rem; background: #fff7ed; border-radius: 16px; color: #9a3412; border: 1px solid #fed7aa; text-align: center;">
                        <h3 style="margin-bottom: 1rem; color: #ea580c;">Match Found!</h3>
                        <p style="font-size: 1.1rem; margin-bottom: 1.5rem;">The station with the most similar profile to <strong>{target_data['name']}</strong> ({target_data['state']}) is:</p>
                        <div style="font-size: 1.5rem; font-weight: 700; margin-bottom: 0.75rem;">{match['Location_Name']} ({match['State']})</div>
                        <p>Both stations average around <strong>{match['Avg_Temp']:.1f}°C</strong></p>
                        <p style="margin-top: 1rem; font-size: 0.9rem; color: #78350f;">Temperature difference: {match['diff']:.1f}°C</p>
                    </div>"""
                else:
                    result_html = "<div class='glass-panel' style='margin-top:2rem; color:#ea580c; padding:1rem;'>Match found, but no similar stations available for comparison.</div>"
            else:
                # Provide helpful suggestions
                sample_ids = list(name_map.keys())[:5]
                sample_names = [f"{name_map[sid].title()} ({sid})" for sid in sample_ids]
                
                result_html = f"""
                <div class='glass-panel' style='margin-top:2rem; padding:2rem; border: 2px solid #fee2e2;'>
                    <p style='color:#dc2626; font-weight:600; margin-bottom:1rem;'>Station '{target_loc}' not found in database.</p>
                    <p style='color:#6b7280; margin-bottom:1rem;'>Please try:</p>
                    <ul style='color:#6b7280; text-align:left; margin-left:2rem; line-height:1.8;'>
                        <li>Using a station ID from the <a href="?page=data" style="color:#ea580c;">Data page</a></li>
                        <li>Entering part of a station name (e.g., "Melbourne", "Brisbane")</li>
                    </ul>
                    <p style='color:#9ca3af; font-size:0.9rem; margin-top:1.5rem;'>Examples: {', '.join(sample_names[:3])}</p>
                </div>"""
            conn.close()
                            
        content = f"""
        <section class="hero"><h1>Similarity Check</h1><p>Compare historical climate profiles across Australia.</p></section>
        <div class="main-container" style="display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: stretch;">
            <div class="glass-panel" style="padding: 4rem; text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <h3 style="margin-bottom: 1.5rem; font-size: 1.6rem;">Find your Climate Twin</h3>
                <p style="color: #4b5563; line-height: 1.8; margin-bottom: 2.5rem; max-width: 400px; margin-left: auto; margin-right: auto;">Our engine analyzes historical temperature patterns to find your city's match.</p>
                <div style="margin-bottom: 2rem;">
                    <h4 style="font-size: 1rem; color: #ea580c; margin-bottom: 1.5rem; text-transform: uppercase;">Use Cases</h4>
                    <ul style="list-style: none; padding: 0; color: #555; line-height: 3; display: inline-block; text-align: left;">
                        <li style="display: flex; align-items: center; gap: 15px;"><i data-lucide="leaf" style="width: 20px; height: 20px; color: #111;"></i> <strong>Gardening:</strong> Find matching thrive zones.</li>
                        <li style="display: flex; align-items: center; gap: 15px;"><i data-lucide="truck" style="width: 20px; height: 20px; color: #111;"></i> <strong>Relocation:</strong> Discover weather you love.</li>
                        <li style="display: flex; align-items: center; gap: 15px;"><i data-lucide="bar-chart-3" style="width: 20px; height: 20px; color: #111;"></i> <strong>Research:</strong> Compare microclimates.</li>
                    </ul>
                </div>
            </div>
            <div class="glass-panel" style="padding: 4rem; text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <form action="/" method="get">
                    <input type="hidden" name="page" value="similarity">
                    <div class="form-group" style="margin-bottom: 2rem;">
                        <label style="margin-bottom: 1.25rem; display: block; font-weight: 600;">Target Station (Name or ID)</label>
                        <input type="text" name="target_loc" placeholder="e.g. Sydney" value="{target_loc if target_loc else ''}" required style="font-size: 1.1rem; padding: 1.2rem; width: 100%;">
                    </div>
                    <button type="submit" class="btn-black" style="margin: 0 auto;">Run Analysis</button>
                </form>
                {result_html}
            </div>
        </div>"""
    
    elif current_page == 'export':
            content = """
            <section class="hero">
                <h1>Export Data</h1>
                <p>Generate and download historical climate datasets for offline analysis.</p>
            </section>
            <div class="main-container" style="max-width: 900px;">
                <div class="glass-panel" style="display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; padding: 4rem; align-items: center;">
                    
                    <div style="text-align: left; border-right: 1px solid rgba(0,0,0,0.05); padding-right: 3rem;">
                        <h3 style="margin-bottom: 1.5rem; font-size: 1.4rem;">Dataset Summary</h3>
                        <p style="color: #6b7280; line-height: 1.6; margin-bottom: 2rem;">Downloads include data from all 7 Australian states and territories, covering records from 1970 to 2020.</p>
                        <div style="display: flex; flex-direction: column; gap: 1rem;">
                            <div style="display: flex; align-items: center; gap: 12px; color: #4b5563; font-size: 0.9rem;">
                                <i data-lucide="file-text" style="width: 18px; height: 18px; color: #ea580c;"></i> CSV Format (Excel Compatible)
                            </div>
                            <div style="display: flex; align-items: center; gap: 12px; color: #4b5563; font-size: 0.9rem;">
                                <i data-lucide="map-pin" style="width: 18px; height: 18px; color: #ea580c;"></i> Includes Location Names
                            </div>
                        </div>
                    </div>

                    <div style="text-align: left; display: flex; flex-direction: column; justify-content: center;">
                        <form action="/download" method="get">
                            <div class="form-group" style="margin-bottom: 2.5rem;">
                                <label style="margin-bottom: 1.25rem; display: block; font-weight: 600;">Configure Download</label>
                                <div style="display: flex; flex-direction: column; gap: 1.25rem;">
                                    <label style="display: flex; align-items: center; gap: 12px; cursor: pointer; font-size: 1rem;">
                                        <input type="checkbox" name="temp" checked style="width: 20px; height: 20px; accent-color: #ea580c;"> 
                                        <span>Temperature Records</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 12px; cursor: pointer; font-size: 1rem;">
                                        <input type="checkbox" name="rain" style="width: 20px; height: 20px; accent-color: #ea580c;"> 
                                        <span>Precipitation Data</span>
                                    </label>
                                </div>
                            </div>
                            <button type="submit" class="btn-black" style="width: 100%; padding: 1.2rem; font-size: 1rem;">
                                <i data-lucide="download" style="width: 18px; height: 18px; vertical-align: middle; margin-right: 8px;"></i>
                                Download CSV
                            </button>
                        </form>
                    </div>

                </div>
            </div>
            """

    elif current_page == 'about':
            content = """
            <section class="hero">
                <h1>The Developer</h1>
                <p>The mind behind the Australian Climate Analytics system.</p>
            </section>
            
            <div class="main-container" style="max-width: 850px; margin-bottom: 0.5rem;">
                <div class="glass-panel" style="text-align: center; padding: 4rem;">
                    <h3 style="font-size: 2.5rem; margin-bottom: 0.5rem;">Tanisha Sinha</h3>
                    <p style="color: #ea580c; font-weight: 600; font-size: 1.1rem; margin-bottom: 1.5rem;">Full-Stack Developer & Data Architect</p>
                    <p style="color: #6b7280; line-height: 1.8; max-width: 650px; margin: 0 auto;">
                        I designed and built this Decision Support System to bridge the gap between complex climate datasets 
                        and actionable insights. By integrating Python-driven analytics with a modern, user-centric interface, 
                        I aim to provide researchers and planners with a seamless tool for historical climate evaluation.
                    </p>
                </div>
            </div>

            <section class="hero" style="padding-top: 0.5rem;">
                <h1 style="margin-bottom: 2rem;">Target Personas</h1>
                <p>Who benefits from Australian Climate Analytics?</p>
            </section>
            
            <div class="main-container grid-container" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 2rem;">
                <div class="glass-panel" style="padding: 2.5rem; text-align: left;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 1rem;">
                        <i data-lucide="microscope" style="color: #ea580c; width: 24px; height: 24px;"></i>
                        <h3 style="font-size: 1.1rem;">Environmental Researchers</h3>
                    </div>
                    <p style="font-size: 0.85rem; color: #6b7280; line-height: 1.6;">Analyzing long-term climate shifts to study impacts on local ecosystems and biodiversity patterns.</p>
                </div>
                
                <div class="glass-panel" style="padding: 2.5rem; text-align: left;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 1rem;">
                        <i data-lucide="sprout" style="color: #ea580c; width: 24px; height: 24px;"></i>
                        <h3 style="font-size: 1.1rem;">Agricultural Planners</h3>
                    </div>
                    <p style="font-size: 0.85rem; color: #6b7280; line-height: 1.6;">Utilizing historical rainfall data to optimize crop cycles and land management strategies.</p>
                </div>

                <div class="glass-panel" style="padding: 2.5rem; text-align: left;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 1rem;">
                        <i data-lucide="home" style="color: #ea580c; width: 24px; height: 24px;"></i>
                        <h3 style="font-size: 1.1rem;">Urban Developers</h3>
                    </div>
                    <p style="font-size: 0.85rem; color: #6b7280; line-height: 1.6;">Leveraging extreme heat records to design climate-resilient housing and sustainable public infrastructure.</p>
                </div>

                <div class="glass-panel" style="padding: 2.5rem; text-align: left;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 1rem;">
                        <i data-lucide="graduation-cap" style="color: #ea580c; width: 24px; height: 24px;"></i>
                        <h3 style="font-size: 1.1rem;">Educational Institutions</h3>
                    </div>
                    <p style="font-size: 0.85rem; color: #6b7280; line-height: 1.6;">Accessing raw datasets for data science projects and geographic historical studies in universities.</p>
                </div>
            </div>
            """

    else: 
        content = """<section class="hero"><h1>Under Construction</h1></section>"""

    # --- 4. BUILD THE TEMPLATE (Updated for darker boxes) ---
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Australian Climate Analytics</title>
        <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <script src="https://unpkg.com/lucide@latest"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Inter', sans-serif; color: #1f2937; background-color: #fcfcfc; background-attachment: fixed; background-size: cover;
                background-image: radial-gradient(circle at 2% 2%, rgba(190, 140, 90, 0.4) 0%, transparent 40%), radial-gradient(circle at 90% 85%, rgba(190, 140, 90, 0.4) 0%, transparent 50%);
                min-height: 100vh; padding-top: 2rem; display: flex; flex-direction: column;

/* --- PRESERVED DESKTOP DESIGN --- */
            nav {{
                position: sticky; 
                top: 2rem; 
                z-index: 1000; 
                display: flex; 
                align-items: center; 
                justify-content: space-between; 
                width: fit-content; 
                max-width: 95%; 
                margin: 0 auto 2rem auto; 
                padding: 0.75rem 2rem; 
                gap: 2rem;
                background: rgba(255, 255, 255, 0.6); 
                backdrop-filter: blur(25px); 
                border: 1px solid rgba(255, 255, 255, 0.8); 
                border-radius: 99px;
                box-shadow: 0 20px 40px -5px rgba(0, 0, 0, 0.15);
            }}

/* --- ZOOM-PROOF MOBILE NAVIGATION --- */
            @media (max-width: 768px) {{
                nav {{
                    width: 95% !important; 
                    padding: 0.5rem 0.8rem !important; 
                    display: flex !important;
                    justify-content: space-between !important; /* Forces logo left, links right */
                    gap: 0 !important; /* Removes the rigid gap that causes overlap */
                }}
                .logo {{ 
                    font-size: 0.85rem !important; 
                    flex-shrink: 0; /* Prevents logo from being squashed */
                    margin-right: 5px !important;
                }}
                .nav-links {{ 
                    display: flex !important;
                    gap: 3px !important; /* Tiny, stable gap for the 7 links */
                    justify-content: flex-end;
                    flex-wrap: nowrap; /* Keeps everything on one line */
                }}
                .nav-links a {{ 
                    font-size: 0.6rem !important; 
                    padding: 0.3rem 0.4rem !important; 
                    white-space: nowrap; /* Prevents link text from breaking */
                }}
                .nav-btn {{
                    padding: 0.3rem 0.6rem !important;
                }}
                .hero h1 {{
                    font-size: 2.8rem !important;
                }}
            }}

/* --- UPDATED HERO & CONTAINER --- */
            .hero h1 {{ 
                font-family: 'DM Serif Display', serif; 
                font-size: 4.5rem; 
                font-weight: 400; 
                line-height: 1.1; 
                margin-bottom: 1.7rem; 
                color: #111; 
                transition: font-size 0.3s ease;
            }}

            .main-container {{ 
                flex-grow: 1; 
                max-width: 1200px; 
                margin: 0 auto; 
                width: 100%; 
                padding: 0 2rem 4rem 2rem; 
            }}

/* --- MOBILE-SPECIFIC ADJUSTMENTS --- */
            @media (max-width: 768px) {{
            

                .hero h1 {{
                    font-size: 2.8rem !important; /* Prevents title overflow on phone */
                    margin-bottom: 1.2rem;
                }}
                .main-container {{ 
                    padding: 0 1.25rem 3rem 1.25rem; /* Better side margins on small screens */
                }}
                .grid-container {{ 
                    grid-template-columns: 1fr; /* Stacks cards vertically for better mobile reading */
                    gap: 1.5rem; 
                }}

            /* Enhanced Mobile Checkbox Fix */
                input[type="checkbox"] {{
                    -webkit-appearance: checkbox; /* Ensures standard look on iOS */
                    width: 26px !important;
                    height: 26px !important;
                    margin-right: 12px !important;
                    cursor: pointer;
                }}
            }}

            .logo {{ font-family: 'DM Serif Display', serif; font-size: 1.4rem; color: #111; letter-spacing: 0.5px; white-space: nowrap; }}
            .logo span {{ color: #ea580c; }}
            .nav-links {{ display: flex; gap: 1rem; list-style: none; align-items: center; margin: 0; }}
            .nav-links a {{ text-decoration: none; color: #4b5563; font-weight: 500; font-size: 0.9rem; transition: all 0.2s ease; padding: 0.5rem 0.8rem; border-radius: 99px; }}
            .nav-btn {{ background-color: #ea580c; color: white !important; box-shadow: 0 4px 10px rgba(234, 88, 12, 0.3); padding: 0.6rem 1.2rem !important; }}
            .hero {{ text-align: center; padding: 3rem 1rem 3rem 1rem; max-width: 1200px; margin: 0 auto; }}

            .hero p {{ color: #555; font-size: 1.125rem; line-height: 1.6; max-width: 600px; margin: 0 auto 1rem auto; }}


/* --- UPDATED: DARKER PANELS & CARDS WITH HOVER --- */
            .glass-panel, .card {{
                background: rgba(255, 255, 255, 0.92); 
                backdrop-filter: blur(10px); 
                border: 1.5px solid rgba(255, 255, 255, 1); 
                border-radius: 24px; 
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06);
                /* This line makes the movement smooth */
                transition: transform 0.3s ease-out, box-shadow 0.3s ease-out;
            }}

            /* This block makes the boxes lift up when you mouse over them */
            .glass-panel:hover, .card:hover {{
                transform: translateY(-8px);
                box-shadow: 0 15px 45px rgba(0, 0, 0, 0.1);
            }}
            
            .glass-panel {{ background: rgba(255, 255, 255, 0.92); backdrop-filter: blur(10px); border: 1.5px solid rgba(255, 255, 255, 1); border-radius: 24px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06); }}
            .grid-container {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 3rem; }}
            /* --- UPDATED: DARKER CARDS --- */
            .card {{ background: rgba(255, 255, 255, 0.92); border: 1.5px solid rgba(255, 255, 255, 1); border-radius: 20px; padding: 2rem; display: flex; flex-direction: column; align-items: flex-start; transition: transform 0.3s cubic-bezier(0.25, 0.8, 0.25, 1); box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05); }}
            .card:hover {{ transform: translateY(-5px); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1); }}
            .card-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 1.25rem; width: 100%; }}
            .card-icon {{ width: 24px; height: 24px; color: #111; }}
            .card h3 {{ font-size: 1.25rem; font-weight: 600; color: #111; margin: 0; }}
            .card p {{ font-size: 0.95rem; color: #6b7280; line-height: 1.5; margin-bottom: 2rem; flex-grow: 1; }}
            .btn-black {{ display: inline-block; background-color: #111; color: white; padding: 0.75rem 1.5rem; border-radius: 8px; text-decoration: none; cursor: pointer; transition: all 0.2s ease; font-weight: 500; border: none; width: fit-content; }}
            .btn-black:hover {{ background-color: #000; transform: translateY(-3px); box-shadow: 0 6px 15px rgba(0,0,0,0.15); }}
            .form-group {{ margin-bottom: 1.5rem; text-align: left; }}
            label {{ display: block; font-weight: 600; margin-bottom: 0.5rem; color: #374151; }}
            input[type="text"], select {{ width: 100%; padding: 0.8rem; border-radius: 8px; border: 1px solid #d1d5db; background: rgba(255,255,255,1); }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th, td {{ padding: 1.2rem; border-top: 1px solid rgba(0,0,0,0.05); color: #4b5563; }}
            .badge-green {{ background: #dcfce7; color: #166534; padding: 0.25rem 0.75rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }}
            footer {{ text-align: center; padding: 2rem; color: #9ca3af; font-size: 0.9rem; margin-top: 2rem; }}
        </style>
    </head>
    <body>
        <nav>
            <div class="logo">CLIMATE<span>.AU</span></div>
            <ul class="nav-links">
                <li><a href="?page=home" class="{'nav-btn' if current_page == 'home' else ''}">Home</a></li>
                <li><a href="?page=data" class="{'nav-btn' if current_page == 'data' else ''}">Data</a></li>
                <li><a href="?page=temps" class="{'nav-btn' if current_page == 'temps' else ''}">Temps</a></li>
                <li><a href="?page=metrics" class="{'nav-btn' if current_page == 'metrics' else ''}">Metrics</a></li>
                <li><a href="?page=similarity" class="{'nav-btn' if current_page == 'similarity' else ''}">Similarity</a></li>
                <li><a href="?page=export" class="{'nav-btn' if current_page == 'export' else ''}">Export</a></li>
                <li><a href="?page=about" class="{'nav-btn' if current_page == 'about' else ''}">About</a></li>
            </ul>
        </nav>
        {content}
        <footer><p>© 2025 Australian Climate Analytics. All rights reserved.</p></footer>
        <script>lucide.createIcons();</script>
    </body>
    </html>
    """
    return html

@app.route('/download')
def download_data():
    include_temp = request.args.get('temp') == 'on'
    include_rain = request.args.get('rain') == 'on'
    
    states = ['VIC', 'NSW', 'QLD', 'WA', 'SA', 'TAS', 'NT']
    all_data = []
    conn = get_db_connection()
    
    # 1. Determine dynamic file name
    if include_temp and include_rain:
        file_label = "Full_Climate_Report"
    elif include_temp:
        file_label = "Temperature_Report"
    else:
        file_label = "Precipitation_Report"

    for state in states:
        try:
            # 2. Updated Query to JOIN and get Location Name
            cols = ["t.Location", "s.name as Location_Name", "t.DMY as Date"]
            if include_temp: cols.append("t.MaxTemp")
            if include_rain: cols.append("t.Precipitation")
            
            query = f"""
                SELECT {', '.join(cols)}, '{state}' as State
                FROM {state} t
                LEFT JOIN weather_station s ON CAST(t.Location AS TEXT) = CAST(s.site_id AS TEXT)
                LIMIT 1000
            """
            df_export = pd.read_sql_query(query, conn)
            all_data.append(df_export)
        except Exception:
            continue
    conn.close()

    if not all_data:
        return "No data available for export.", 404

    final_df = pd.concat(all_data, ignore_index=True)
    
    # Clean up Location_Name formatting
    if 'Location_Name' in final_df.columns:
        final_df['Location_Name'] = final_df['Location_Name'].str.title()
    
    proxy = io.StringIO()
    final_df.to_csv(proxy, index=False)
    
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode('utf-8'))
    mem.seek(0)
    proxy.close()

    # 3. Use the unique file_label here
    return send_file(
        mem,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'australian_{file_label}.csv'
    )



@app.route('/')

def home():
    return get_page_html(request.args)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
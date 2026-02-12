import flet as ft
import os
import sys
import time
import threading

# Add Orchestrator Root to Path for Imports
# File: .../Executive/Orchestrator/ui/dashboard_window.py
ui_dir = os.path.dirname(os.path.abspath(__file__)) 
orch_dir = os.path.dirname(ui_dir) # .../Executive/Orchestrator
project_root = os.path.dirname(os.path.dirname(orch_dir)) # .../

print(f"DEBUG: UI Dir: {ui_dir}")
print(f"DEBUG: Orch Dir: {orch_dir}")

if orch_dir not in sys.path:
    sys.path.insert(0, orch_dir)

from core.dashboard_generator import generate_dashboard

# Theme Constants (Matching Main App)
GLASS_COLOR = "#1AFFFFFF" # 10% White
GLASS_BORDER = "#33FFFFFF" # 20% White
PCP_RED = "#c62127"

def main(page: ft.Page):
    page.title = "PCP Nexus | Live Operations Board"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0f172a"
    page.padding = 20
    page.window_width = 1000
    page.window_height = 800
    
    # Force window to front using Always on Top toggle
    page.window_always_on_top = True
    page.update()
    time.sleep(0.5)
    page.window_always_on_top = False # Release after bringing to front
    page.update()
    
    # -- COMPONENT BUILDERS --
    def metric_card(label, value, color, icon):
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon, color=color, size=24),
                ft.Text(str(value), size=28, weight="bold", color="white"),
                ft.Text(label, size=12, color="white54")
            ], alignment="center", horizontal_alignment="center"),
            bgcolor=GLASS_COLOR,
            border=ft.border.all(1, GLASS_BORDER),
            border_radius=10,
            padding=20,
            width=180
        )

    # Dynamic Containers
    metrics_row = ft.Row([], alignment="center", spacing=20)
    action_view = ft.Column([], scroll=ft.ScrollMode.AUTO)
    recent_view = ft.Column([], scroll=ft.ScrollMode.AUTO)
    last_updated_text = ft.Text("Initializing...", size=10, color="white30")

    def refresh_data():
        while True:
            try:
                data = generate_dashboard(output_mode='data')
                if data is None:
                    print("DEBUG: generate_dashboard returned None (DB not ready?)")
                    
                if data:
                    # Update Metrics
                    metrics_row.controls = [
                        metric_card("24h Volume", data['period_jobs'], "white", "insert_chart"),
                        metric_card("Filing Rate", f"{data['success_rate']}%", "green", "check_circle"),
                        metric_card("Duplicates", data['dup_count'], "amber", "content_copy"),
                        metric_card("Action Items", len(data['action_items']), "red", "warning"),
                    ]
                    
                    # Update Action Items
                    # We rebuild the DataTable to avoid complex row diffing
                    action_dt = ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text("ID")),
                            ft.DataColumn(ft.Text("Env ID")),
                            ft.DataColumn(ft.Text("Case #")),
                            ft.DataColumn(ft.Text("Lead Doc")),
                            ft.DataColumn(ft.Text("Reason", width=150)),
                        ],
                        rows=[
                            ft.DataRow(cells=[
                                ft.DataCell(ft.Text(str(r['id']))),
                                ft.DataCell(ft.Text(r.get('envelope_id','-'), size=10, font_family="Consolas")),
                                ft.DataCell(ft.Text(r.get('case_num','-'), size=10)),
                                ft.DataCell(ft.Text(str(r.get('lead_doc','-'))[:25]+'...', size=10, tooltip=str(r.get('lead_doc','-')))),
                                ft.DataCell(ft.Text(r.get('reason', 'Check Logs'), size=10, color="orange")),
                            ]) for r in data['action_items']
                        ],
                        heading_row_color="#2d2d2d",
                        data_row_color={"hovered": "#3d3d3d"},
                        divider_thickness=0,
                        column_spacing=10
                    )
                    action_view.controls = [action_dt]

                    # Update Recent Items
                    recent_dt = ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text("ID")),
                            ft.DataColumn(ft.Text("Old File")), # Renamed from Old Pfx
                            ft.DataColumn(ft.Text("New File")), # Renamed from New Pfx
                            ft.DataColumn(ft.Text("Status")),
                            ft.DataColumn(ft.Text("File Location", width=250)),
                        ],
                        rows=[
                            ft.DataRow(cells=[
                                ft.DataCell(ft.Text(str(r['id']))),
                                ft.DataCell(ft.Text(str(r.get('old_file','-'))[:20]+'...', size=10, weight="bold", tooltip=r.get('old_file','-'))),
                                ft.DataCell(ft.Text(str(r.get('new_file','-'))[:20]+'...', size=10, color="cyan", tooltip=r.get('new_file','-'))),
                                ft.DataCell(ft.Text(r['status'], color="green", size=10)),
                                ft.DataCell(ft.Text(str(r.get('file_path_short','-')), size=9, tooltip=r.get('file_path','-'))), 
                            ]) for r in data['recent_items']
                        ],
                         heading_row_color="#2d2d2d",
                         divider_thickness=0,
                         column_spacing=10
                    )
                    recent_view.controls = [recent_dt]
                    
                    recent_view.controls = [recent_dt]
                    
                    # Failure Analytics (Charts)
                    f_stats = data.get('failure_stats', {})
                    if f_stats and (f_stats.get('by_type') or f_stats.get('by_stage')):
                        
                        def create_mini_chart(title, data_dict, color_seed):
                            if not data_dict: return ft.Container()
                            
                            groups = []
                            keys = list(data_dict.keys())
                            max_val = max(data_dict.values()) if data_dict.values() else 1
                            
                            for i, k in enumerate(keys):
                                val = data_dict[k]
                                groups.append(
                                    ft.BarChartGroup(
                                        x=i,
                                        bar_rods=[
                                            ft.BarChartRod(
                                                from_y=0,
                                                to_y=val,
                                                width=16,
                                                color=color_seed,
                                                tooltip=f"{k}: {val}",
                                                border_radius=0
                                            )
                                        ],
                                    )
                                )
                            
                            return ft.Container(
                                content=ft.Column([
                                    ft.Text(title, size=14, weight="bold", color="white70"),
                                    ft.BarChart(
                                        bar_groups=groups,
                                        border=ft.border.all(1, "white10"),
                                        left_axis=ft.ChartAxis(labels_size=30, title_size=10),
                                        bottom_axis=ft.ChartAxis(
                                            labels=[
                                                ft.ChartAxisLabel(
                                                    value=i, 
                                                    label=ft.Container(
                                                        content=ft.Text(k, size=10, text_align="right"), 
                                                        rotate=ft.Rotate(-0.5), # -0.5 radians approx -30 degrees? No, Flet rotate is radians. -0.5 is ~ -28 deg.
                                                        padding=ft.padding.only(top=10)
                                                    )
                                                ) for i, k in enumerate(keys)
                                            ],
                                            labels_size=60, # Increased height for rotated text
                                        ),
                                        horizontal_grid_lines=ft.ChartGridLines(color="white10", width=1, dash_pattern=[3, 3]),
                                        tooltip_bgcolor="#111111",
                                        max_y=max_val * 1.2,
                                        interactive=True,
                                        expand=True,
                                    )
                                ]),
                                height=300,  # Increased Height
                                width=400,   # Increased Width
                                bgcolor=GLASS_COLOR,
                                border_radius=10,
                                padding=25   # Increased Padding for Tooltips
                            )

                        c1 = create_mini_chart("By Type", f_stats.get('by_type', {}), "#3b82f6") # Blue
                        c2 = create_mini_chart("By Stage", f_stats.get('by_stage', {}), "#f59e0b") # Orange
                        c3 = create_mini_chart("By Reason", f_stats.get('by_reason', {}), "#ef4444") # Red

                        failure_container.content = ft.Row([c1, c2, c3], spacing=10, scroll=ft.ScrollMode.AUTO)
                        failure_container.visible = True
                    else:
                        failure_container.visible = False

                    # Update Timestamp

                    # Update Timestamp
                    import datetime
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    last_updated_text.value = f"Last Refresh: {ts}"

                    page.update()
                
            except Exception as e:
                print(f"Dashboard Refresh Error: {e}")
            
            time.sleep(2) # Refresh Rate
    
    # New Failure Container
    failure_container = ft.Container(visible=False, padding=10)

    # Layout
    page.add(
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("LIVE ANALYTICS (24h Window)", size=20, weight="bold"),
                    ft.Container(expand=True),
                    last_updated_text
                ]),
                ft.Divider(color="white10", height=20),
                metrics_row,
                failure_container, # Inserted here
                ft.Divider(color="transparent", height=20),
                ft.Row([
                    ft.Container(content=ft.Column([ft.Text("Action Required", weight="bold", color="red"), action_view], scroll=ft.ScrollMode.AUTO), expand=True, bgcolor=GLASS_COLOR, border_radius=10, padding=10),
                    ft.Container(content=ft.Column([ft.Text("Recent Success", weight="bold", color="green"), recent_view], scroll=ft.ScrollMode.AUTO), expand=True, bgcolor=GLASS_COLOR, border_radius=10, padding=10),
                ], expand=True)
            ]),
            expand=True
        )
    )

    # Start Background Thread for Data
    t = threading.Thread(target=refresh_data, daemon=True)
    t.start()

if __name__ == "__main__":
    ft.app(target=main)

import time
import smtplib
import ssl
import os
import pandas
import pandas as pd
from email.message import EmailMessage
from flask import Flask, render_template
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, time, timedelta
import openpyxl
from openpyxl.chart import BarChart, LineChart, Reference

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///battery_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

class BatteryData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(80), nullable=False)
    production_datetime = db.Column(db.String(80), nullable=False)
    shift = db.Column(db.String(80), nullable=False)
    master_model = db.Column(db.String(80), nullable=False)
    line = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# Create the database tables if they don't exist
with app.app_context():
    db.create_all()

@app.route('/')
def form():
    return render_template('form.html')

@app.route('/submit', methods=['POST'])
def submit():
    product_id = request.form.get('product_id')
    shift = request.form.get('shift')
    master_model = request.form.get('master_model')
    line = request.form.get('line')

    # Automatically get the current date and time
    production_datetime = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    # Check if the battery number has already been posted
    if BatteryData.query.filter_by(product_id=product_id).first():
        return jsonify({'error': 'Battery pack number has already been posted.'}), 400

    # Validate master model against the product_id prefix
    if (master_model == "KE242080" and not product_id.startswith("TB6")) or \
       (master_model == "KE242620" and not product_id.startswith("TBB")) or \
       (master_model == "KE240400" and not product_id.startswith("TB2")):
        return jsonify({'error': f'Invalid product ID for selected master model {master_model}.'}), 400
    
    
    # Create and save the new battery data
    new_data = BatteryData(
        product_id=product_id,
        production_datetime=production_datetime,
        shift=shift,
        master_model=master_model,
        line=line,
        timestamp=datetime.now()
    )
    db.session.add(new_data)
    db.session.commit()

    return jsonify({'message': 'Battery pack number successfully posted.'}), 201

@app.route('/dashboard/<line>')
def dashboard(line):
    now = datetime.now()
    shift_start_time = time(7, 0)
    report_saved = False  # To track if the report is saved for the last shift
     
    # Determine the current shift and set start datetime accordingly
    if time(7, 0) <= now.time() < time(15, 29,29):
        current_shift = "1st"
        start_datetime = datetime.combine(now.date(), time(7, 0))
        previous_shift = "3rd"
        previous_shift_start = datetime.combine(now.date() - timedelta(days=1), time(0, 0))
        previous_shift_end = datetime.combine(now.date(), time(6, 59, 59))
    elif time(15, 30) <= now.time() < time(23, 59, 59):
        current_shift = "2nd"
        start_datetime = datetime.combine(now.date(), time(15, 30))
        previous_shift = "1st"
        previous_shift_start = datetime.combine(now.date(), time(7, 0))
        previous_shift_end = datetime.combine(now.date(), time(15, 29, 29))
    else:
        current_shift = "3rd"
        start_datetime = datetime.combine(now.date(), time(0, 0))
        previous_shift = "2nd"
        previous_shift_start = datetime.combine(now.date() - timedelta(days=1), time(15, 30))
        previous_shift_end = datetime.combine(now.date(), time(23, 59, 59))

    # **Trigger report generation at shift change**
    if now.time() == start_datetime.time():  # Check if it's the start of a new shift
        generate_shift_report(previous_shift, previous_shift_start, previous_shift_end)

    # Fetch battery data for the current shift and specific line
    battery_data = BatteryData.query.filter(
        BatteryData.timestamp >= start_datetime,
        BatteryData.timestamp <= now,
        BatteryData.line == line
    ).all()
    # Fetch and save data for the previous shift
    previous_shift_data = BatteryData.query.filter(
        BatteryData.timestamp >= previous_shift_start,
        BatteryData.timestamp < previous_shift_end
    ).all()

    if previous_shift_data:
        # Define the report directory and ensure it exists
        report_dir = "D:/battery_reports"
        os.makedirs(report_dir, exist_ok=True)  

        # Generate the file path
        report_file_path = os.path.join(report_dir, f"{previous_shift}_{previous_shift_start.date()}.xlsx")

        # Check if report already exists, if so, do not overwrite
        if os.path.exists(report_file_path):
            print(f"Report for {previous_shift} already exists. Skipping save.")
            return  # Exit the function to prevent overwriting

        # Convert data to a Pandas DataFrame
        df = pd.DataFrame([{
            "Serial No": i + 1,
            "ID": data.id,
            "Product ID": data.product_id,
            "Production DateTime": data.production_datetime,
            "Shift": data.shift,
            "Master Model": data.master_model,
            "Line": data.line,
            "Timestamp": data.timestamp
        } for i, data in enumerate(previous_shift_data)])

        # Aggregate shift, day, and month counts
        shift_counts = df["Master Model"].value_counts().reset_index()
        shift_counts.columns = ["Master Model", "Shift Count"]

        day_counts = BatteryData.query.filter(
            BatteryData.timestamp >= datetime.combine(previous_shift_start.date(), time(0, 0))
        ).all()
        df_day = pd.DataFrame([{"Master Model": data.master_model} for data in day_counts])
        day_counts = df_day["Master Model"].value_counts().reset_index()
        day_counts.columns = ["Master Model", "Day Count"]

        month_counts = BatteryData.query.filter(
            BatteryData.timestamp >= datetime.combine(previous_shift_start.replace(day=1), time(0, 0))
        ).all()
        df_month = pd.DataFrame([{"Date": data.timestamp.date(), "Master Model": data.master_model} for data in month_counts])
        month_counts = df_month.groupby("Date").size().reset_index(name="Cumulative Count")
        month_counts["Cumulative Count"] = month_counts["Cumulative Count"].cumsum()

        # Save to Excel
        with pd.ExcelWriter(report_file_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Shift Report")
            shift_counts.to_excel(writer, index=False, sheet_name="Shift Count")
            day_counts.to_excel(writer, index=False, sheet_name="Day vs Month Count")
            month_counts.to_excel(writer, index=False, sheet_name="Day vs Month Count", startcol=4)

            wb = writer.book
            ws = wb["Day vs Month Count"]

            # Create Bar Chart for Daily Count
            bar_chart = BarChart()
            bar_data = Reference(ws, min_col=2, min_row=2, max_row=len(day_counts) + 1)
            bar_categories = Reference(ws, min_col=1, min_row=2, max_row=len(day_counts) + 1)
            bar_chart.add_data(bar_data, titles_from_data=True)
            bar_chart.set_categories(bar_categories)
            bar_chart.title = "Daily Output"
            ws.add_chart(bar_chart, "E2")

            # Create Line Chart for Monthly Cumulative Output
            line_chart = LineChart()
            line_data = Reference(ws, min_col=5, min_row=2, max_row=len(month_counts) + 1)
            line_categories = Reference(ws, min_col=4, min_row=2, max_row=len(month_counts) + 1)
            line_chart.add_data(line_data, titles_from_data=True)
            line_chart.set_categories(line_categories)
            line_chart.title = "Monthly Cumulative Output"
            ws.add_chart(line_chart, "E16")

        # Update the flag after successful report saving
        print(f"Report saved at: {report_file_path}")
        report_saved = True  # Mark report as saved
    
   # Plan calculations based on actual shift duration
    total_plan = 500 if current_shift != "3rd" else 400
    actual_so_far = len(battery_data)

    # Hourly plans and actual output tracking
    hourly_plans = [58, 66, 57, 65, 66, 65, 57, 66] if current_shift != "3rd" else [58, 64, 58, 33, 64, 58, 66]
    actual_per_hour = [0] * len(hourly_plans)

    # Define hourly timings for each shift
    hourly_timings = {
        "1st": [
            (time(7, 0), time(8, 0)), (time(8, 0), time(9, 0)),
            (time(9, 0), time(10, 0)), (time(10, 0), time(11, 0)),
            (time(11, 0), time(12, 30)), (time(12, 30), time(13, 30)),
            (time(13, 30), time(14, 30)), (time(14, 30), time(15, 29, 29))
        ],
        "2nd": [
            (time(15, 30), time(16, 30)), (time(16, 30), time(17, 30)),
            (time(17, 30), time(18, 30)), (time(18, 30), time(19, 30)),
            (time(19, 30), time(21, 0)), (time(21, 0), time(22, 0)),
            (time(22, 0), time(23, 0)), (time(23, 0), time(23, 59, 59))
        ],
        "3rd": [
            (time(0, 0), time(1, 0)), (time(1, 0), time(2, 0)),
            (time(2, 0), time(3, 0)), (time(3, 0), time(4, 0)),
            (time(4, 0), time(5, 0)), (time(5, 0), time(6, 0)),
            (time(6, 0), time(6, 59, 59))
        ]
    }
    for data in battery_data:
        data_time = data.timestamp.time()
        for i, (start_time, end_time) in enumerate(hourly_timings[current_shift]):
            if start_time <= data_time < end_time:
                actual_per_hour[i] += 1

    # Plan vs actual calculations
    elapsed_seconds = (now - start_datetime).total_seconds()
    plan_so_far = min(int(elapsed_seconds // 61.2), total_plan)
    actual_so_far = len(battery_data)
    gap = plan_so_far - actual_so_far
    percentage_achieved = (actual_so_far / total_plan) * 100 if total_plan > 0 else 0

    return render_template('dashboard.html',
                           actual_so_far=len(battery_data),
                           total_plan=total_plan,
                           plan_so_far=plan_so_far,
                           gap=gap,
                           percentage_achieved=percentage_achieved,
                           hourly_plans=hourly_plans,
                           actual_per_hour=actual_per_hour,
                           current_shift=current_shift)

if __name__ == '__main__':
    app.run(debug=True) 
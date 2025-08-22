from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime
import io
import random

app = Flask(__name__)
app.secret_key = 'secret'  # change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ration.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------ Models ------------------------

class Distributor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))


class Beneficiary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    aadhar_number = db.Column(db.String(12), unique=True)
    address = db.Column(db.String(200))
    ration_card_no = db.Column(db.String(50))
    family_members = db.Column(db.Integer)
    status = db.Column(db.String(20), default='Pending')


class RationItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100))
    quantity_available = db.Column(db.Float)
    unit = db.Column(db.String(20))
    price_per_unit = db.Column(db.Float)
    distribution_date = db.Column(db.Date)


class RationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey('beneficiary.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='Pending', nullable=False)


class DistributionRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey('beneficiary.id'))
    item_type = db.Column(db.String(100))
    quantity = db.Column(db.Float)
    distribution_date = db.Column(db.Date)
    distributor_id = db.Column(db.Integer, db.ForeignKey('distributor.id'))

# ---------------------- Init Data -----------------------

@app.before_request
def initialize():
    db.create_all()

    # Add default admin user if not present
    if not Distributor.query.filter_by(username='admin').first():
        admin = Distributor(
            name="Admin",
            username="admin",
            password=generate_password_hash("admin123", method='pbkdf2:sha256')
        )
        db.session.add(admin)

    # Populate 10 demo beneficiaries
    if Beneficiary.query.count() < 10:
        Beneficiary.query.delete()
        for i in range(1, 11):
            db.session.add(Beneficiary(
                name=f"Demo{i}",
                aadhar_number=f"{100000000000+i}",
                address="Demo Address",
                ration_card_no=f"RC{i:05d}",
                family_members=(i % 5) + 2
            ))
    db.session.commit()

# ----------------------- Routes -------------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user = Distributor.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['distributor_id'] = user.id
            flash("Login successful!", "success")
            return redirect(url_for('dashboard_page'))
        else:
             flash("Invalid username or password. Try again.", "error")
             return redirect(url_for("index") + "#login-modal")

    return render_template("index.html")

@app.route('/dashboard_page')
def dashboard_page():
    return render_template("dashboard_page.html")


@app.route('/add_ration', methods=['GET', 'POST'])
def add_ration():
    if request.method == 'POST':
        try:
            item = RationItem(
                item_name=request.form['item_name'],
                quantity_available=float(request.form['quantity']),
                unit=request.form['unit'],
                price_per_unit=float(request.form['price_per_unit']),
                distribution_date=datetime.strptime(request.form['distribution_date'], '%Y-%m-%d')
            )
            db.session.add(item)
            db.session.commit()
            flash("Ration item added successfully!", "success")
            return redirect(url_for('view_ration'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding item: {e}", "danger")
    return render_template("add_ration.html")


@app.route('/view_ration')
def view_ration():
    items = RationItem.query.all()
    return render_template("view_ration.html", items=items)


@app.route("/ration_distribution", methods=["GET", "POST"])
def ration_distribution():
    if request.method == "POST":
        beneficiary_id = request.form["beneficiaryId"]
        item_type = request.form["itemType"]
        quantity = request.form["quantity"]
        distribution_date = request.form["distribution_date"]

        # Save record in DB
        record = DistributionRecord(
            beneficiary_id=beneficiary_id,
            item_type=item_type,
            quantity=float(quantity),
            distribution_date=datetime.strptime(distribution_date, "%Y-%m-%d"),
            distributor_id=session.get("distributor_id")  # logged in user
        )
        db.session.add(record)
        db.session.commit()

        # Generate receipt no
        receipt_no = f"REC-{datetime.now().strftime('%Y%m%d')}-{random.randint(100,999)}"

        flash(f"✅ Ration Distributed Successfully to Beneficiary ID {beneficiary_id}", "success")

        # Redirect to receipt page
        return redirect(url_for(
            "receipt",
            receipt_no=receipt_no,
            beneficiary_id=beneficiary_id,
            item_type=item_type,
            quantity=quantity,
            date_dist=distribution_date  # ✅ matches receipt()
        ))

    return render_template("ration_distribution.html")


        
# 🔹 Route: Show Receipt (HTML)
@app.route("/receipt")
def receipt():
    receipt_no = request.args.get("receipt_no")
    beneficiary_id = request.args.get("beneficiary_id")
    item_type = request.args.get("item_type")
    quantity = request.args.get("quantity")
    date_dist = request.args.get("date_dist")  # ✅ now consistent

    return render_template(
        "receipt.html",
        receipt_no=receipt_no,
        beneficiary_id=beneficiary_id,
        item_type=item_type,
        quantity=quantity,
        date_dist=date_dist
    )

@app.route("/download_receipt")
def download_receipt():
    receipt_no = request.args.get("receipt_no")
    beneficiary_id = request.args.get("beneficiary_id")
    item_type = request.args.get("item_type")
    quantity = request.args.get("quantity")
    date_dist = request.args.get("date_dist")

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Title
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, height - 50, "Ration Distribution Receipt")

    # Details
    p.setFont("Helvetica", 12)
    y = height - 100
    p.drawString(100, y, f"Receipt No: {receipt_no}")
    y -= 20
    p.drawString(100, y, f"Beneficiary ID: {beneficiary_id}")
    y -= 20
    p.drawString(100, y, f"Item Type: {item_type}")
    y -= 20
    p.drawString(100, y, f"Quantity: {quantity}")
    y -= 20
    p.drawString(100, y, f"Date of Distribution: {date_dist}")

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"receipt_{beneficiary_id}.pdf",
                     mimetype='application/pdf')


@app.route('/ration_requests', methods=['GET', 'POST'])
def ration_requests():
    beneficiaries = Beneficiary.query.all()
    if request.method == 'POST':
        try:
            req = RationRequest(
                beneficiary_id=int(request.form['beneficiary_id']),
                item_name=request.form['item_name'],
                unit=request.form['unit'],
                month=request.form['month']
            )
            db.session.add(req)
            db.session.commit()
            flash("Request submitted successfully.", "success")
            return redirect(url_for('dashboard_page'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")
    return render_template("ration_requests.html", beneficiaries=beneficiaries)


@app.route('/view_beneficiary_list')
def view_beneficiary_list():
    beneficiaries = Beneficiary.query.all()
    return render_template("view_beneficiary_list.html", beneficiaries=beneficiaries)


@app.route('/update_status', methods=['POST'])
def update_status():
    b = Beneficiary.query.get(int(request.form['beneficiary_id']))
    b.status = request.form['status']
    db.session.commit()
    flash("Status updated successfully.", "info")
    return redirect(url_for('view_beneficiary_list'))


@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('index'))

@app.route('/edit_ration/<int:id>', methods=['GET', 'POST'])
def edit_ration(id):
    item = RationItem.query.get_or_404(id)
    if request.method == 'POST':
        item.item_name = request.form['item_name']
        item.quantity_available = float(request.form['quantity'])
        item.unit = request.form['unit']
        item.price_per_unit = float(request.form['price_per_unit'])
        item.distribution_date = datetime.strptime(request.form['distribution_date'], '%Y-%m-%d')
        db.session.commit()
        flash("Item updated successfully!", "info")
        return redirect(url_for('view_ration'))
    return render_template('edit_ration.html', item=item)

@app.route('/delete_ration/<int:id>')
def delete_ration(id):
    item = RationItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.", "info")
    return redirect(url_for('view_ration'))

# ---------------------- Main ----------------------------

if __name__ == '__main__':
    app.run(debug=True)
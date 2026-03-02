from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Project, Deployment
from . import db

from datetime import datetime
import pytz
import time
import random

main = Blueprint("main", __name__)


# -----------------------------
# Home / Dashboard
# -----------------------------
@main.route("/")
@login_required
def home():

    projects = Project.query.filter_by(user_id=current_user.id).all()
    project_data = []

    for project in projects:
        latest_deployment = (
            Deployment.query
            .filter_by(project_id=project.id)
            .order_by(Deployment.created_at.desc())
            .first()
        )

        project_data.append({
            "project": project,
            "deployment": latest_deployment
        })

    return render_template("dashboard.html", project_data=project_data)


# -----------------------------
# Register
# -----------------------------
@main.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        # Check duplicate email
        if User.query.filter_by(email=email).first():
            return render_template(
                "register.html",
                error="Email already registered."
            )

        # Check duplicate username
        if User.query.filter_by(username=username).first():
            return render_template(
                "register.html",
                error="Username already taken."
            )

        user = User(
            username=username,
            email=email,
            password=password
        )

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("main.login"))

    return render_template("register.html")


# -----------------------------
# Login
# -----------------------------
@main.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if not user:
            return render_template(
                "login.html",
                error="Email not found."
            )

        if not check_password_hash(user.password, password):
            return render_template(
                "login.html",
                error="Incorrect password."
            )

        login_user(user)
        return redirect(url_for("main.home"))

    return render_template("login.html")


# -----------------------------
# Logout
# -----------------------------
@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


# -----------------------------
# Create Project
# -----------------------------
@main.route("/projects/create", methods=["GET", "POST"])
@login_required
def create_project():

    if request.method == "POST":
        name = request.form["name"]
        github_repo = request.form["github_repo"]

        project = Project(
            name=name,
            github_repo=github_repo,
            user_id=current_user.id
        )

        db.session.add(project)
        db.session.commit()

        return redirect(url_for("main.home"))

    return render_template("create_project.html")


# -----------------------------
# Deploy Project
# -----------------------------
@main.route("/projects/<int:project_id>/deploy")
@login_required
def deploy(project_id):

    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    start_time = datetime.utcnow()

    deployment = Deployment(
        project_id=project.id,
        status="Running",
        logs="Starting deployment...\nCloning repository...\nBuilding Docker image...\n",
        created_at=start_time
    )

    db.session.add(deployment)
    db.session.commit()

    time.sleep(2)

    if random.choice([True, False]):
        deployment.status = "Success"
        deployment.logs += "\nDeployment completed successfully!"
    else:
        deployment.status = "Failed"
        deployment.logs += "\nDeployment failed during build step."

    end_time = datetime.utcnow()

    deployment.completed_at = end_time
    deployment.duration = (end_time - start_time).total_seconds()

    db.session.commit()

    return redirect(url_for("main.home"))


# -----------------------------
# Deployment History
# -----------------------------
@main.route("/projects/<int:project_id>/deployments")
@login_required
def project_deployments(project_id):

    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    deployments = (
        Deployment.query
        .filter_by(project_id=project.id)
        .order_by(Deployment.created_at.desc())
        .all()
    )

    # Convert UTC to IST
    ist = pytz.timezone("Asia/Kolkata")

    for deployment in deployments:
        if deployment.created_at:
            deployment.local_time = (
                deployment.created_at
                .replace(tzinfo=pytz.utc)
                .astimezone(ist)
            )
        else:
            deployment.local_time = None

    return render_template(
        "deployment_history.html",
        project=project,
        deployments=deployments
    )


# -----------------------------
# View Logs
# -----------------------------
@main.route("/deployments/<int:deployment_id>/logs")
@login_required
def view_logs(deployment_id):

    deployment = Deployment.query.get_or_404(deployment_id)

    if deployment.project.user_id != current_user.id:
        return "Unauthorized", 403

    return render_template("logs.html", deployment=deployment)
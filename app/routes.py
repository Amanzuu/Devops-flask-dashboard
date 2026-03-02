from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Project, Deployment
from . import db
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
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        user = User(username=username, email=email, password=password)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("main.login"))

    return render_template("register.html")


# -----------------------------
# Login
# -----------------------------
@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
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
# Projects Page (Optional Separate View)
# -----------------------------
@main.route("/projects")
@login_required
def projects():

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

    # Secure: ensure project belongs to current user
    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    deployment = Deployment(
        project_id=project.id,
        status="Running",
        logs="Starting deployment...\nCloning repository...\nBuilding Docker image...\n"
    )

    db.session.add(deployment)
    db.session.commit()

    # Simulate deployment delay
    time.sleep(2)

    # Simulate random success/failure
    if random.choice([True, False]):
        deployment.status = "Success"
        deployment.logs += "\nDeployment completed successfully!"
    else:
        deployment.status = "Failed"
        deployment.logs += "\nDeployment failed during build step."

    db.session.commit()

    return redirect(url_for("main.home"))

# -----------------------------
# Add routes
# -----------------------------
@main.route("/projects/<int:project_id>/deployments")
@login_required
def project_deployments(project_id):

    # Ensure project belongs to logged-in user
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

    return render_template(
        "deployment_history.html",
        project=project,
        deployments=deployments
    )

# -----------------------------
# View Deployment Logs
# -----------------------------
@main.route("/deployments/<int:deployment_id>/logs")
@login_required
def view_logs(deployment_id):

    deployment = Deployment.query.get_or_404(deployment_id)

    # Security check: ensure deployment belongs to current user
    if deployment.project.user_id != current_user.id:
        return "Unauthorized", 403

    return render_template("logs.html", deployment=deployment)
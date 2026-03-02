from flask import Blueprint, render_template, redirect, url_for, request, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Project, Deployment
from . import db

import os
import subprocess
from datetime import datetime
from threading import Thread

main = Blueprint("main", __name__)


# ==================================================
# BACKGROUND DEPLOYMENT FUNCTION
# ==================================================
def run_deployment_async(app, deployment_id):

    with app.app_context():

        deployment = db.session.get(Deployment, deployment_id)
        if not deployment:
            return

        project = deployment.project

        base_dir = os.path.join(os.getcwd(), "deployments")
        os.makedirs(base_dir, exist_ok=True)

        project_path = os.path.join(base_dir, f"project_{project.id}")

        try:
            deployment.progress = 10
            db.session.commit()

            # ------------------ CLONE OR PULL ------------------
            if os.path.exists(project_path):

                deployment.logs += "\nRepository exists. Pulling latest changes..."
                db.session.commit()

                subprocess.run(
                    ["git", "-C", project_path, "pull"],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore"
                )
            else:
                deployment.logs += f"\nCloning into '{project_path}'..."
                db.session.commit()

                subprocess.run(
                    ["git", "clone", project.github_repo, project_path],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore"
                )

            deployment.progress = 30
            db.session.commit()

            # ------------------ CHECK DOCKERFILE ------------------
            dockerfile_path = os.path.join(project_path, "Dockerfile")
            if not os.path.exists(dockerfile_path):
                deployment.status = "Failed"
                deployment.logs += "\nDockerfile not found."
                deployment.progress = 100
                db.session.commit()
                return

            image_name = f"project_{project.id}_image"
            container_name = f"project_{project.id}_container"
            port = 5000 + project.id

            # Remove old container if exists
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True
            )

            # ------------------ BUILD IMAGE ------------------
            deployment.logs += "\nBuilding Docker image..."
            db.session.commit()

            subprocess.run(
                ["docker", "build", "-t", image_name, "."],
                cwd=project_path,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )

            deployment.progress = 70
            db.session.commit()

            # ------------------ RUN CONTAINER ------------------
            deployment.logs += "\nStarting container..."
            db.session.commit()

            subprocess.run(
                [
                    "docker", "run", "-d",
                    "-p", f"{port}:5000",
                    "--name", container_name,
                    image_name
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )

            deployment.status = "Success"
            deployment.port = port
            deployment.logs += "\nDeployment completed successfully!"
            deployment.progress = 100

        except subprocess.CalledProcessError as e:
            deployment.status = "Failed"
            deployment.logs += f"\nError:\n{e.stderr}"
            deployment.progress = 100

        deployment.completed_at = datetime.utcnow()
        deployment.duration = (
            deployment.completed_at - deployment.created_at
        ).total_seconds()

        db.session.commit()


# ==================================================
# HOME / DASHBOARD
# ==================================================
@main.route("/")
@login_required
def home():

    projects = Project.query.filter_by(user_id=current_user.id).all()
    project_data = []

    for project in projects:
        latest = (
            Deployment.query
            .filter_by(project_id=project.id)
            .order_by(Deployment.created_at.desc())
            .first()
        )

        project_data.append({
            "project": project,
            "deployment": latest
        })

    return render_template("dashboard.html", project_data=project_data)


# ==================================================
# REGISTER
# ==================================================
@main.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        if User.query.filter_by(email=email).first():
            return render_template("register.html", error="Email already registered.")

        if User.query.filter_by(username=username).first():
            return render_template("register.html", error="Username already taken.")

        user = User(username=username, email=email, password=password)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("main.login"))

    return render_template("register.html")


# ==================================================
# LOGIN
# ==================================================
@main.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if not user:
            return render_template("login.html", error="Email not found.")

        if not check_password_hash(user.password, password):
            return render_template("login.html", error="Incorrect password.")

        login_user(user)
        return redirect(url_for("main.home"))

    return render_template("login.html")


# ==================================================
# LOGOUT
# ==================================================
@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


# ==================================================
# CREATE PROJECT
# ==================================================
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


# ==================================================
# DEPLOY ROUTE
# ==================================================
@main.route("/projects/<int:project_id>/deploy")
@login_required
def deploy(project_id):

    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    deployment = Deployment(
        project_id=project.id,
        status="Running",
        logs="Starting deployment...\n",
        created_at=datetime.utcnow(),
        progress=0
    )

    db.session.add(deployment)
    db.session.commit()

    thread = Thread(
        target=run_deployment_async,
        args=(current_app._get_current_object(), deployment.id)
    )
    thread.daemon = True
    thread.start()

    return redirect(url_for("main.home"))


# ==================================================
# STOP PROJECT
# ==================================================
@main.route("/projects/<int:project_id>/stop")
@login_required
def stop_project(project_id):

    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    container_name = f"project_{project.id}_container"

    subprocess.run(["docker", "rm", "-f", container_name],
                   capture_output=True, text=True)

    latest = (
        Deployment.query
        .filter_by(project_id=project.id)
        .order_by(Deployment.created_at.desc())
        .first()
    )

    if latest:
        latest.status = "Stopped"
        db.session.commit()

    return redirect(url_for("main.home"))


# ==================================================
# DEPLOYMENT HISTORY
# ==================================================
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

    return render_template(
        "deployment_history.html",
        project=project,
        deployments=deployments
    )

# ==================================================
# VIEW DEPLOYMENT LOGS
# ==================================================
@main.route("/deployments/<int:deployment_id>/logs")
@login_required
def view_logs(deployment_id):

    deployment = db.session.get(Deployment, deployment_id)

    if not deployment:
        return "Not Found", 404

    if deployment.project.user_id != current_user.id:
        return "Unauthorized", 403

    return render_template("logs.html", deployment=deployment)

# ==================================================
# DEPLOYMENT STATUS API
# ==================================================
@main.route("/deployment-status/<int:deployment_id>")
@login_required
def deployment_status(deployment_id):

    deployment = db.session.get(Deployment, deployment_id)

    if not deployment:
        return jsonify({"error": "Not found"}), 404

    if deployment.project.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify({
        "status": deployment.status,
        "progress": deployment.progress,
        "port": deployment.port
    })
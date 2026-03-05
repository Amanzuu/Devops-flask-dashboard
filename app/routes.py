from flask import Blueprint, render_template, redirect, url_for, request, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Project, Deployment
from . import db

import os
import subprocess
import time
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

            # ---------------- CLONE / PULL ----------------
            if os.path.exists(project_path):

                deployment.logs += "\n📦 Pulling latest changes...\n"

                result = subprocess.run(
                    ["git", "-C", project_path, "pull"],
                    capture_output=True,
                    text=True
                )

                deployment.logs += result.stdout

            else:

                deployment.logs += "\n📥 Cloning repository...\n"

                result = subprocess.run(
                    ["git", "clone", project.github_repo, project_path],
                    capture_output=True,
                    text=True
                )

                deployment.logs += result.stdout

            deployment.progress = 30
            db.session.commit()

            # ---------------- DOCKERFILE CHECK ----------------
            if not os.path.exists(os.path.join(project_path, "Dockerfile")):

                deployment.status = "Failed"
                deployment.logs += "\n❌ Dockerfile not found.\n"
                deployment.progress = 100
                db.session.commit()
                return

            image_name = f"project_{project.id}_image"
            container_name = f"project_{project.id}_container"
            port = 5000 + project.id

            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

            # ---------------- BUILD IMAGE ----------------
            deployment.logs += "\n🔨 Building Docker image...\n"
            db.session.commit()

            build = subprocess.Popen(
                ["docker", "build", "-t", image_name, "."],
                cwd=project_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in build.stdout:
                deployment.logs += line
                db.session.commit()

            build.wait()

            if build.returncode != 0:
                deployment.status = "Failed"
                deployment.progress = 100
                db.session.commit()
                return

            deployment.progress = 70
            db.session.commit()

            # ---------------- RUN CONTAINER ----------------
            deployment.logs += "\n🚀 Starting container...\n"

            run = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "-d",
                    "--restart",
                    "unless-stopped",
                    "-p",
                    f"{port}:5000",
                    "--name",
                    container_name,
                    image_name
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            container_id = None

            for line in run.stdout:
                deployment.logs += line
                container_id = line.strip()
                db.session.commit()

            run.wait()

            if run.returncode != 0:
                deployment.status = "Failed"
                deployment.progress = 100
                db.session.commit()
                return

            deployment.container_id = container_id
            deployment.port = port
            deployment.progress = 90
            db.session.commit()

            # ---------------- HEALTH CHECK ----------------
            deployment.logs += "\n🔍 Checking application health...\n"

            if is_app_responding(container_name):
                deployment.logs += "\n✅ Application responding successfully!\n"
                deployment.status = "Success"
            else:
                deployment.logs += "\n⚠ Container running but HTTP check failed.\n"
                deployment.status = "Success"

            deployment.progress = 100

        except Exception as e:

            deployment.status = "Failed"
            deployment.logs += f"\n❌ Error: {str(e)}\n"
            deployment.progress = 100

        deployment.completed_at = datetime.utcnow()

        if deployment.created_at:
            deployment.duration = (
                deployment.completed_at - deployment.created_at
            ).total_seconds()

        db.session.commit()


# ==================================================
# CHECK CONTAINER STATE
# ==================================================
def is_container_running(container_name):

    try:

        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True
        )

        return result.returncode == 0 and result.stdout.strip() == "true"

    except Exception:
        return False


# ==================================================
# HEALTH CHECK
# ==================================================
def is_app_responding(container_name, retries=5):

    for _ in range(retries):

        try:

            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_name,
                    "curl",
                    "-s",
                    "http://localhost:5000"
                ],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return True

        except Exception:
            pass

        time.sleep(2)

    return False


# ==================================================
# HOME DASHBOARD
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
# AUTH ROUTES
# ==================================================
@main.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        user = User(
            username=request.form["username"],
            email=request.form["email"],
            password=generate_password_hash(request.form["password"])
        )

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("main.login"))

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        user = User.query.filter_by(email=request.form["email"]).first()

        if user and check_password_hash(user.password, request.form["password"]):

            login_user(user)
            return redirect(url_for("main.home"))

    return render_template("login.html")


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

        project = Project(
            name=request.form["name"],
            github_repo=request.form["github_repo"],
            user_id=current_user.id
        )

        db.session.add(project)
        db.session.commit()

        return redirect(url_for("main.home"))

    return render_template("create_project.html")


# ==================================================
# DEPLOY
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

    container_name = f"project_{project_id}_container"

    subprocess.run(["docker", "rm", "-f", container_name])

    latest = Deployment.query.filter_by(
        project_id=project_id
    ).order_by(Deployment.created_at.desc()).first()

    if latest:
        latest.status = "Stopped"
        db.session.commit()

    return redirect(url_for("main.home"))


# ==================================================
# DELETE PROJECT
# ==================================================
@main.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):

    project = Project.query.filter_by(
        id=project_id,
        user_id=current_user.id
    ).first_or_404()

    container_name = f"project_{project.id}_container"
    image_name = f"project_{project.id}_image"

    # stop & remove container
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    # remove docker image
    subprocess.run(["docker", "rmi", "-f", image_name], capture_output=True)

    # remove deployment folder
    project_path = os.path.join(
        os.getcwd(),
        "deployments",
        f"project_{project.id}"
    )

    if os.path.exists(project_path):
        import shutil
        shutil.rmtree(project_path)

    # delete deployments from DB
    Deployment.query.filter_by(project_id=project.id).delete()

    # delete project
    db.session.delete(project)
    db.session.commit()

    return redirect(url_for("main.home"))

# ==================================================
# HISTORY PAGE
# ==================================================

@main.route("/deployment-history/<int:deployment_id>")
@login_required
def deployment_history(deployment_id):

    deployment = Deployment.query.get_or_404(deployment_id)

    container_logs = deployment.logs or "No logs available"

    return render_template(
        "deployment_history.html",
        deployment=deployment,
        logs=container_logs,
        container_id="N/A",
        git_commit="N/A"
    )

# ==================================================
# DEPLOYMENT STATUS API
# ==================================================
@main.route("/deployment-status/<int:deployment_id>")
@login_required
def deployment_status(deployment_id):

    deployment = db.session.get(Deployment, deployment_id)

    if not deployment or deployment.project.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify({
        "status": deployment.status,
        "progress": deployment.progress,
        "port": deployment.port
    })

# ==================================================
# API ROUTE
# ==================================================
    
@main.route("/api/docker-stats")
@login_required
def docker_stats():

    try:

        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Container}}|{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"
            ],
            capture_output=True,
            text=True
        )

        containers = []

        for line in result.stdout.strip().split("\n"):

            if not line:
                continue

            cid, name, cpu, mem = line.split("|")

            containers.append({
                "id": cid,
                "name": name,
                "cpu": cpu,
                "memory": mem
            })

        return jsonify(containers)

    except Exception as e:

        return jsonify({"error": str(e)})
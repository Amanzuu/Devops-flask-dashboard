from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Project
from . import db
from .models import User, Project, Deployment

main = Blueprint("main", __name__)

@main.route("/")
@login_required
def home():
    projects = Project.query.filter_by(user_id=current_user.id).all()
    return render_template("dashboard.html", projects=projects)

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

@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))

@main.route("/projects")
@login_required
def projects():
    projects = Project.query.filter_by(user_id=current_user.id).all()
    return render_template("projects.html", projects=projects)

@main.route("/projects/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        name = request.form["name"]
        github_repo = request.form["github_repo"]

        project = Project(name=name, github_repo=github_repo, user_id=current_user.id)
        db.session.add(project)
        db.session.commit()

        return redirect(url_for("main.projects"))

    return render_template("create_project.html")

#Deploye route

import time
import random

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
        logs="Starting deployment...\nCloning repository...\nBuilding Docker image...\n"
    )

    db.session.add(deployment)
    db.session.commit()

    time.sleep(2)

    if random.choice([True, False]):
        deployment.status = "Success"
        deployment.logs += "Deployment completed successfully!"
    else:
        deployment.status = "Failed"
        deployment.logs += "Deployment failed during build step."

    db.session.commit()

    return redirect(url_for("main.home"))
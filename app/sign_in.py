from flask import render_template, url_for, session, redirect, request, flash, send_from_directory
from app import webapp

@webapp.route('/login', methods=["GET", "POST"])
def login():
    if(request.method == 'POST'):
        return do_login(request.form)
    else:
        return render_template("login_form.html")

@webapp.route('/logout', methods=["POST"])
def logout():
    if (session.get('username') is not None and session['username'] == webapp.config['ROOT_USER']):
        session.pop('username', None)
        flash("INFO: logout successful")
        return redirect(url_for('login'))
    return redirect('/')


def do_login(form):
    if (form):
        username = form.get("username")
        password = form.get("password")

        if(username == webapp.config['ROOT_USER'] and password == webapp.config['ROOT_PASSWORD']):
            session['username'] = username
            return redirect('/')
        flash("Incorrect username or password")
        return redirect('/')

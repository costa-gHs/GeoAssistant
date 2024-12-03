from flask_sqlalchemy import SQLAlchemy
from datetime import datetime as dt

db = SQLAlchemy()

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    data_ultimo_login = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)

    conversas = db.relationship('Conversa', backref='usuario', lazy=True)


class Conversa(db.Model):
    __tablename__ = 'conversas'
    id = db.Column(db.Integer, primary_key=True)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    data_inicio = db.Column(db.DateTime, default=dt.utcnow)
    thread_id = db.Column(db.String(255), nullable=True)
    mensagens = db.relationship('Mensagem', backref='conversa', lazy=True)


class Mensagem(db.Model):
    __tablename__ = 'mensagens'
    id = db.Column(db.Integer, primary_key=True)
    id_conversa = db.Column(db.Integer, db.ForeignKey('conversas.id'), nullable=False)
    texto_usuario = db.Column(db.Text, nullable=False)
    texto_gpt = db.Column(db.Text, nullable=True)
    data_hora_envio = db.Column(db.DateTime, default=dt.utcnow)

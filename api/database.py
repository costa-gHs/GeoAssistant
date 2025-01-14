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
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())

    # Relacionamentos
    conversas = db.relationship('Conversa', backref='usuario', lazy=True, cascade="all, delete-orphan")
    api_keys = db.relationship('APIKey', backref='usuario', lazy=True)
    limites = db.relationship('UserLimit', backref='usuario', uselist=False)

class APIKey(db.Model):
    __tablename__ = 'api_keys'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    empresa = db.Column(db.String, nullable=False)
    projeto = db.Column(db.String)
    chave = db.Column(db.String, nullable=False)
    expires_at = db.Column(db.DateTime)
    last_used_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active')

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

class UserLimit(db.Model):
    __tablename__ = 'user_limits'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    limite_tokens_mensal = db.Column(db.Integer)
    limite_conversas_mensal = db.Column(db.Integer)
    alerta_uso_porcentagem = db.Column(db.Integer)
    ativo = db.Column(db.Boolean, default=True)

# Em database.py
class UserUsageMetric(db.Model):
    __tablename__ = 'user_usage_metrics'
    id = db.Column(db.BigInteger, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    data_referencia = db.Column(db.Date)
    total_tokens = db.Column(db.Integer, default=0)
    total_conversas = db.Column(db.Integer, default=0)
    total_mensagens = db.Column(db.Integer, default=0)
    custo_estimado = db.Column(db.Numeric)
    created_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True))

    usuario = db.relationship('Usuario', backref='usage_metrics')
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from flask import abort
from openai import OpenAI
import time
import secrets
import bcrypt
from api.admin_routes import admin_routes_bp  # Novo nome do Blueprint
from api.database import db, Usuario, Conversa, Mensagem  # Importa db e modelos
from datetime import datetime as dt

app = Flask(__name__, static_folder='../static', template_folder='../templates')
app.secret_key = secrets.token_hex(16)

# Configuração do banco de dados
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///usuarios.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Registra o Blueprint de administração
app.register_blueprint(admin_routes_bp, url_prefix='/admin')  # Rotas administrativas

# Funções auxiliares
def iniciar_conversa(usuario_id):
    nova_conversa = Conversa(id_usuario=usuario_id)
    db.session.add(nova_conversa)
    db.session.commit()
    return nova_conversa

def salvar_mensagem(id_conversa, texto_usuario, texto_gpt):
    nova_mensagem = Mensagem(
        id_conversa=id_conversa,
        texto_usuario=texto_usuario,
        texto_gpt=texto_gpt
    )
    db.session.add(nova_mensagem)
    db.session.commit()

def carregar_historico(usuario_id):
    conversas = Conversa.query.filter_by(id_usuario=usuario_id).all()
    historico = []
    for conversa in conversas:
        mensagens = Mensagem.query.filter_by(id_conversa=conversa.id).all()
        historico.append({
            "conversa_id": conversa.id,
            "data_inicio": conversa.data_inicio,
            "mensagens": [{"usuario": m.texto_usuario, "gpt": m.texto_gpt, "data": m.data_hora_envio} for m in mensagens]
        })
    return historico

# Função para listar os assistentes existentes com nomes e IDs
def get_assistants():
    try:
        api_key = session.get('api_key')
        if not api_key:
            return []
        client = OpenAI(api_key=api_key)
        response = client.beta.assistants.list(order="desc", limit=20)
        assistant_list = [{"id": assistant.id, "name": assistant.name or 'Sem Nome'} for assistant in response.data]
        return assistant_list
    except Exception as e:
        print(f"Erro ao buscar assistentes: {e}")
        return []

# Funções auxiliares que usam o cliente OpenAI
def create_thread(client):
    try:
        thread = client.beta.threads.create()
        print(f"Thread criada: {thread.id}")  # Debug
        return thread.id
    except Exception as e:
        print(f"Erro ao criar um tópico: {e}")
        return None

def send_message(client, thread_id, user_message):
    try:
        client.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=user_message
        )
        print(f"Mensagem enviada para thread {thread_id}")  # Debug
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def run_thread(client, thread_id, assistant_id):
    try:
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )
        print(f"Thread {thread_id} executada com assistant_id {assistant_id}")  # Debug
        return run
    except Exception as e:
        print(f"Erro ao executar o tópico: {e}")
        return None

def get_response(client, thread_id):
    try:
        response = client.beta.threads.messages.list(thread_id=thread_id, order="asc")
        return response
    except Exception as e:
        print(f"Erro ao obter resposta: {e}")
        return None

def get_assistant_reply(messages):
    # Percorre as mensagens em ordem reversa para obter a resposta mais recente
    for message in reversed(messages.data):
        if message.role == 'assistant':
            content_blocks = message.content
            for block in content_blocks:
                if block.type == 'text':
                    text = block.text.value
                    print(f"Resposta do assistente encontrada: {text}")  # Debug
                    return text  # Retorna o texto da mensagem mais recente do assistente
    return None

# Rota principal
@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    usuario_nome = session.get('usuario_nome', 'Usuário')
    is_admin = session.get('is_admin', False)

    # Busca assistentes do OpenAI
    assistants = get_assistants()

    # Carrega o histórico de conversas
    historico = carregar_historico(usuario_id)

    # Passa o histórico para o template
    return render_template(
        'index.html',
        usuario_nome=usuario_nome,
        is_admin=is_admin,
        assistants=assistants,
        historico=historico
    )


# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        api_key = request.form.get('api_key')

        usuario = Usuario.query.filter_by(nome=nome).first()

        if usuario and bcrypt.checkpw(senha.encode('utf-8'), usuario.senha.encode('utf-8')):
            session['usuario_id'] = usuario.id
            session['usuario_nome'] = usuario.nome
            session['is_admin'] = usuario.is_admin  # Adiciona status de administrador à sessão
            session['api_key'] = api_key

            usuario.data_ultimo_login = dt.now()
            db.session.commit()

            # Redireciona para o chat após login
            return redirect(url_for('index'))

        return render_template('login.html', error='Nome ou senha incorretos.')

    return render_template('login.html')


@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    data = request.get_json()
    api_key = data.get('api_key')
    if api_key:
        session['api_key'] = api_key
        session.pop('thread_id', None)
        session.pop('assistant_id', None)
        print("API key definida. Sessão atualizada.")  # Debug
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Chave da API ausente'}), 400

# Função para enviar mensagem
@app.route('/chat', methods=['POST'])
def chat():
    if 'api_key' not in session:
        return jsonify({'error': 'Chave da API não definida'}), 400

    api_key = session.get('api_key')
    client = OpenAI(api_key=api_key)

    data = request.get_json()
    assistant_id = data.get('assistant_id')
    user_message = data.get('message')
    conversa_id = data.get('conversa_id')  # Pode ser None

    if not assistant_id or not user_message:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    # Se não houver conversa_id, cria uma nova conversa
    if not conversa_id:
        usuario_id = session['usuario_id']
        nova_conversa = iniciar_conversa(usuario_id)
        conversa_id = nova_conversa.id
        thread_id = create_thread(client)
        if not thread_id:
            return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
        nova_conversa.thread_id = thread_id
        db.session.commit()
    else:
        # Recupera conversa existente
        conversa = db.session.get(Conversa, conversa_id)
        if not conversa:
            return jsonify({'error': 'Conversa não encontrada.'}), 404
        thread_id = conversa.thread_id

    # Garante que a thread_id existe
    if not thread_id:
        thread_id = create_thread(client)
        if not thread_id:
            return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
        conversa.thread_id = thread_id
        db.session.commit()

    print(f"Usando thread_id: {thread_id}")

    # Envia mensagem e executa a thread
    if not send_message(client, thread_id, user_message):
        return jsonify({'error': 'Erro ao enviar a mensagem.'}), 500

    run_response = run_thread(client, thread_id, assistant_id)
    if not run_response:
        return jsonify({'error': 'Erro ao executar o tópico.'}), 500

    # Polling para obter a resposta
    max_wait_time = 60
    poll_interval = 5
    total_waited = 0
    resposta = None

    while total_waited < max_wait_time:
        time.sleep(poll_interval)
        total_waited += poll_interval
        resposta_suja = get_response(client, thread_id)
        if resposta_suja:
            resposta = get_assistant_reply(resposta_suja)
            if resposta:
                break

    if resposta:
        salvar_mensagem(conversa_id, user_message, resposta)
        return jsonify({'response': resposta, 'conversa_id': conversa_id})
    else:
        return jsonify({'error': 'Não foi possível obter uma resposta do assistente.'}), 500



@app.route('/conversa/<int:conversa_id>')
def get_conversa(conversa_id):
    usuario_id = session.get('usuario_id')
    conversa = db.session.get(Conversa, conversa_id)

    if not conversa or conversa.id_usuario != usuario_id:
        return jsonify({'error': 'Conversa não encontrada ou não pertence ao usuário atual'}), 404

    # Imprime o thread_id no terminal
    print(f"Thread ID da conversa {conversa_id}: {conversa.thread_id}")

    mensagens = Mensagem.query.filter_by(id_conversa=conversa.id).order_by(Mensagem.data_hora_envio.asc()).all()

    mensagens_json = [
        {
            'usuario': mensagem.texto_usuario,
            'gpt': mensagem.texto_gpt,
            'data_hora_envio': mensagem.data_hora_envio.strftime('%d/%m/%Y %H:%M')
        }
        for mensagem in mensagens
    ]

    # Armazena o thread_id na sessão
    session['thread_id'] = conversa.thread_id
    session['conversa_id'] = conversa_id  # Garante que a conversa atual está na sessão

    return jsonify({'mensagens': mensagens_json, 'thread_id': conversa.thread_id})


@app.route('/nova_conversa', methods=['POST'])
def nova_conversa():
    nova_conversa = iniciar_conversa(session['usuario_id'])
    session['conversa_id'] = nova_conversa.id
    return jsonify({
        'success': True,
        'conversa_id': nova_conversa.id,
        'data_inicio': nova_conversa.data_inicio.strftime('%d/%m/%Y %H:%M')
    })

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)

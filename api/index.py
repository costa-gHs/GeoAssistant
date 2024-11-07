from flask import Flask, request, render_template, jsonify, session
from openai import OpenAI
import time
import secrets  # Importa o módulo secrets para gerar a secret_key

app = Flask(__name__, static_folder='../static', template_folder='../templates')
app.secret_key = secrets.token_hex(16)  # Gera uma secret_key segura

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

@app.route('/')
def index():
    # Verifica se a chave da API está na sessão
    if 'api_key' not in session:
        return render_template('index.html', assistants=[])
    assistants = get_assistants()
    if not assistants:
        return render_template('index.html', assistants=[], error='Erro ao carregar assistentes. Verifique sua chave da API.')
    return render_template('index.html', assistants=assistants)

@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    data = request.get_json()
    api_key = data.get('api_key')
    if api_key:
        session['api_key'] = api_key
        # Limpa a thread_id e assistant_id ao definir uma nova API key
        session.pop('thread_id', None)
        session.pop('assistant_id', None)
        print("API key definida. Sessão atualizada.")  # Debug
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Chave da API ausente'}), 400

@app.route('/chat', methods=['POST'])
def chat():
    # Verifica se a chave da API está na sessão
    if 'api_key' not in session:
        return jsonify({'error': 'Chave da API não definida'}), 400

    api_key = session.get('api_key')
    client = OpenAI(api_key=api_key)

    data = request.get_json()
    assistant_id = data.get('assistant_id')
    user_message = data.get('message')

    if not assistant_id or not user_message:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    # Armazena o assistant_id na sessão se ainda não estiver lá
    if 'assistant_id' not in session:
        session['assistant_id'] = assistant_id
        print(f"assistant_id definido na sessão: {assistant_id}")  # Debug
    else:
        # Verifica se o assistant_id mudou e reinicia a thread se necessário
        if session['assistant_id'] != assistant_id:
            session['assistant_id'] = assistant_id
            session.pop('thread_id', None)
            print(f"assistant_id mudou. thread_id reiniciado.")  # Debug

    # Recupera ou cria a thread
    thread_id = session.get('thread_id')
    if not thread_id:
        # Criar um novo tópico
        thread_id = create_thread(client)
        if not thread_id:
            return jsonify({'error': 'Não foi possível criar um novo tópico.'}), 500
        session['thread_id'] = thread_id  # Armazena o thread_id na sessão
        print(f"thread_id armazenado na sessão: {thread_id}")  # Debug
    else:
        print(f"thread_id recuperado da sessão: {thread_id}")  # Debug
        # Verifica se a thread ainda é válida
        try:
            client.beta.threads.retrieve(thread_id=thread_id)
        except Exception as e:
            print(f"Thread inválida ou expirada: {e}")
            # Criar um novo tópico se a anterior não for válida
            thread_id = create_thread(client)
            if not thread_id:
                return jsonify({'error': 'Não foi possível criar um novo tópico.'}), 500
            session['thread_id'] = thread_id  # Atualiza o thread_id na sessão
            print(f"thread_id atualizado na sessão: {thread_id}")  # Debug

    # Enviar mensagem ao tópico
    if not send_message(client, thread_id, user_message):
        return jsonify({'error': 'Não foi possível enviar a mensagem.'}), 500

    # Executar o tópico com o assistente
    run_response = run_thread(client, thread_id, session['assistant_id'])
    if not run_response:
        return jsonify({'error': 'Não foi possível executar o tópico.'}), 500

    # Aguardar a resposta com polling
    max_wait_time = 60  # Aumenta o tempo máximo de espera para 60 segundos
    poll_interval = 5   # Intervalo entre as verificações em segundos
    total_waited = 0
    resposta_suja = None

    while total_waited < max_wait_time:
        time.sleep(poll_interval)
        total_waited += poll_interval

        # Obter a resposta
        resposta_suja = get_response(client, thread_id)
        if not resposta_suja:
            continue  # Se falhar ao obter a resposta, tenta novamente

        resposta = get_assistant_reply(resposta_suja)
        if resposta:
            break  # Sai do loop se obtiver uma resposta

    if resposta:
        return jsonify({'response': resposta})
    else:
        return jsonify({'error': 'Não foi possível obter uma resposta do assistente após várias tentativas.'}), 500

if __name__ == '__main__':
    app.run(debug=True)

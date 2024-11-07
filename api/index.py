from flask import Flask, request, render_template, jsonify, session
from openai import OpenAI
import time

app = Flask(__name__, static_folder='../static', template_folder='../templates')
app.secret_key = 'sua_chave_secreta'  # Substitua por uma chave secreta segura

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
        return client.beta.threads.create()
    except Exception as e:
        print(f"Erro ao criar um tópico: {e}")
        return None

def send_message(client, thread, user_message):
    try:
        client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=user_message
        )
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def run_thread(client, thread, assistant_id):
    try:
        return client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id,
        )
    except Exception as e:
        print(f"Erro ao executar o tópico: {e}")
        return None

def get_response(client, thread):
    try:
        response = client.beta.threads.messages.list(thread_id=thread.id, order="asc")
        return response
    except Exception as e:
        print(f"Erro ao obter resposta: {e}")
        return None

def get_assistant_reply(messages):
    for message in messages.data:
        if message.role == 'assistant':
            content_blocks = message.content
            for block in content_blocks:
                if block.type == 'text':
                    text = block.text.value
                    return text  # Retorna o primeiro texto de resposta do assistente
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

    resposta = None  # Inicializa a resposta

    for attempt in range(3):  # Tenta até 3 vezes
        print(f"Tentativa {attempt + 1} de 3")
        # Criar um novo tópico
        thread = create_thread(client)
        if not thread:
            continue  # Se falhar ao criar o tópico, tenta novamente

        # Enviar mensagem ao tópico
        if not send_message(client, thread, user_message):
            continue  # Se falhar ao enviar a mensagem, tenta novamente

        # Executar o tópico com o assistente
        run_response = run_thread(client, thread, assistant_id)
        if not run_response:
            continue  # Se falhar ao executar o tópico, tenta novamente

        # Aguardar um tempo para o assistente processar a mensagem
        time.sleep(5)

        # Obter a resposta
        resposta_suja = get_response(client, thread)
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

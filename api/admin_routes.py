from flask import Blueprint, render_template, jsonify, session, request, redirect, url_for
from api.database import db, Usuario, Conversa, Mensagem
import bcrypt
from api.supabase_client import supabase, get_api_key
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from collections import defaultdict
from openai import OpenAI
import time
import os

admin_routes_bp = Blueprint('admin_routes', __name__)

# Armazenamento temporário de arquivos
temp_file_storage = {}

# Dashboard
@admin_routes_bp.route('/dashboard')
def dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    try:
        response = supabase.table("usuarios").select("id, nome").execute()
        usuarios = response.data
    except Exception as e:
        print(f"Erro ao buscar usuários: {e}")
        usuarios = []

    return render_template('dashboard.html', usuarios=usuarios)

@admin_routes_bp.route('/metricas/tokens/usuarios', methods=['GET'])
def obter_metricas_tokens_usuarios():
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    dias = request.args.get('dias', default=30, type=int)
    usuario_id = request.args.get('usuario_id', type=int)

    try:
        # Query base para métricas de tokens
        query = supabase.from_('token_metrics') \
            .select("""
                *,
                usuarios (
                    nome
                )
            """) \
            .gte('timestamp', (datetime.now() - timedelta(days=dias)).isoformat())

        if usuario_id:
            query = query.eq('usuario_id', usuario_id)

        response = query.execute()

        # Organizar dados por usuário
        usuarios_metricas = defaultdict(lambda: {
            'nome': '',
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_tokens': 0,
            'metricas_diarias': defaultdict(lambda: {
                'input': 0,
                'output': 0,
                'total': 0
            })
        })

        for metric in response.data:
            usuario_id = metric['usuario_id']
            usuarios_metricas[usuario_id]['nome'] = metric['usuarios']['nome']
            usuarios_metricas[usuario_id]['total_input_tokens'] += metric['input_tokens']
            usuarios_metricas[usuario_id]['total_output_tokens'] += metric['output_tokens']
            usuarios_metricas[usuario_id]['total_tokens'] += metric['total_tokens']

            # Agregar por dia
            dia = datetime.fromisoformat(metric['timestamp']).strftime('%Y-%m-%d')
            usuarios_metricas[usuario_id]['metricas_diarias'][dia]['input'] += metric['input_tokens']
            usuarios_metricas[usuario_id]['metricas_diarias'][dia]['output'] += metric['output_tokens']
            usuarios_metricas[usuario_id]['metricas_diarias'][dia]['total'] += metric['total_tokens']

        # Buscar limites dos usuários
        limites_response = supabase.table('user_limits').select('*').execute()
        limites = {
            limite['usuario_id']: limite['limite_tokens_mensal']
            for limite in limites_response.data
        }

        # Adicionar informação de limites e percentual de uso
        for usuario_id, metricas in usuarios_metricas.items():
            limite = limites.get(usuario_id, 0)
            if limite > 0:
                metricas['limite_mensal'] = limite
                metricas['percentual_uso'] = (metricas['total_tokens'] / limite) * 100
            else:
                metricas['limite_mensal'] = 0
                metricas['percentual_uso'] = 0

        return jsonify({
            'usuarios': dict(usuarios_metricas),
            'periodo_dias': dias
        })

    except Exception as e:
        print(f"Erro ao obter métricas: {e}")
        return jsonify({'error': str(e)}), 500

# Gerenciamento de usuários
@admin_routes_bp.route('/usuarios', methods=['GET', 'POST'])
def listar_usuarios():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        is_admin = bool(request.form.get('is_admin'))

        hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
        novo_usuario = Usuario(nome=nome, senha=hashed_password.decode('utf-8'), is_admin=is_admin)

        try:
            db.session.add(novo_usuario)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Erro ao adicionar usuário: {e}'}), 400

    usuarios = Usuario.query.all()
    return render_template('usuarios.html', usuarios=usuarios)

@admin_routes_bp.route('/usuarios/excluir/<int:usuario_id>', methods=['POST'])
def excluir_usuario(usuario_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    try:
        supabase.table("usuarios").delete().eq("id", usuario_id).execute()
        return redirect(url_for('admin_routes.listar_usuarios'))
    except Exception as e:
        return jsonify({'error': f'Erro ao excluir usuário: {e}'}), 400

# Gerenciamento de conversas
@admin_routes_bp.route('/conversas', methods=['GET'])
def listar_conversas():
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado.'}), 403

    conversas = Conversa.query.join(Usuario).all()
    return render_template('conversas.html', conversas=conversas)

@admin_routes_bp.route('/conversas/excluir/<int:conversa_id>', methods=['POST'])
def excluir_conversa(conversa_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado.'}), 403

    conversa = Conversa.query.get(conversa_id)
    if conversa:
        db.session.delete(conversa)
        db.session.commit()
        return jsonify({'success': 'Conversa excluída com sucesso.'}), 200
    return jsonify({'error': 'Conversa não encontrada.'}), 404

# Gerenciamento de mensagens
@admin_routes_bp.route('/mensagens/<int:conversa_id>', methods=['GET'])
def listar_mensagens(conversa_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado.'}), 403

    conversa = Conversa.query.get_or_404(conversa_id)
    mensagens = Mensagem.query.filter_by(id_conversa=conversa_id).all()
    return render_template(
        'mensagens.html',
        mensagens=mensagens,
        conversa_id=conversa_id,
        usuario_nome=conversa.usuario.nome
    )

@admin_routes_bp.route('/mensagens/excluir/<int:mensagem_id>', methods=['POST'])
def excluir_mensagem(mensagem_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado.'}), 403

    mensagem = Mensagem.query.get(mensagem_id)
    if mensagem:
        db.session.delete(mensagem)
        db.session.commit()
        return jsonify({'success': 'Mensagem excluída com sucesso.'}), 200
    return jsonify({'error': 'Mensagem não encontrada.'}), 404

@admin_routes_bp.route('/metricas/feedback')
def obter_metricas_feedback():
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        periodo = request.args.get('dateRange', 'all')
        tipo_feedback = request.args.get('feedbackType', 'all')
        modelo = request.args.get('model', 'all')
        busca = request.args.get('searchTerm', '')

        query = supabase.from_('vw_feedback_metricas').select('*')

        if periodo != 'all':
            if periodo == 'today':
                query = query.gte('data_feedback', datetime.now().date().isoformat())
            elif periodo == 'week':
                query = query.gte('data_feedback', (datetime.now() - timedelta(days=7)).isoformat())
            elif periodo == 'month':
                query = query.gte('data_feedback', (datetime.now() - timedelta(days=30)).isoformat())

        if tipo_feedback != 'all':
            query = query.eq('feedback_tipo', tipo_feedback == 'positive')

        if modelo != 'all':
            query = query.eq('modelo_nome', modelo)

        if busca:
            query = query.ilike('comentario', f'%{busca}%')

        response = query.execute()
        feedbacks = response.data

        total_feedbacks = len(feedbacks)
        feedbacks_positivos = sum(1 for f in feedbacks if f.get('feedback_tipo', False))
        feedbacks_negativos = total_feedbacks - feedbacks_positivos
        taxa_satisfacao = (feedbacks_positivos / total_feedbacks * 100) if total_feedbacks > 0 else 0

        feedbacks_por_modelo = {}
        for feedback in feedbacks:
            modelo = feedback.get('modelo_nome') or 'Desconhecido'
            if modelo not in feedbacks_por_modelo:
                feedbacks_por_modelo[modelo] = {
                    'positivos': 0,
                    'negativos': 0,
                    'total': 0
                }

            if feedback.get('feedback_tipo', False):
                feedbacks_por_modelo[modelo]['positivos'] += 1
            else:
                feedbacks_por_modelo[modelo]['negativos'] += 1
            feedbacks_por_modelo[modelo]['total'] += 1

            feedbacks_por_modelo[modelo]['taxa_satisfacao'] = (
                feedbacks_por_modelo[modelo]['positivos'] / feedbacks_por_modelo[modelo]['total'] * 100
                if feedbacks_por_modelo[modelo]['total'] > 0 else 0
            )

        feedbacks_data = [{
            'feedback_id': f.get('feedback_id'),
            'feedback_tipo': f.get('feedback_tipo'),
            'comentario': f.get('comentario'),
            'data_feedback': f.get('data_feedback'),
            'mensagem_id': f.get('mensagem_id'),
            'modelo': f.get('modelo'),
            'input_tokens': f.get('input_tokens'),
            'output_tokens': f.get('output_tokens'),
            'usuario_id': f.get('usuario_id'),
            'id_modelo': f.get('id_modelo'),
            'usuario_nome': f.get('usuario_nome'),
            'texto_usuario': f.get('texto_usuario'),
            'texto_gpt': f.get('texto_gpt'),
            'id_conversa': f.get('id_conversa'),
            'modelo_nome': f.get('modelo_nome'),
            'modelo_empresa': f.get('modelo_empresa')
        } for f in feedbacks]

        return jsonify({
            'taxa_satisfacao': taxa_satisfacao,
            'total_feedbacks': total_feedbacks,
            'feedbacks_positivos': feedbacks_positivos,
            'feedbacks_negativos': feedbacks_negativos,
            'feedbacks_por_modelo': feedbacks_por_modelo,
            'feedbacks': feedbacks_data
        })

    except Exception as e:
        print(f"Erro ao obter métricas de feedback: {e}")
        return jsonify({'error': str(e)}), 500

@admin_routes_bp.route('/visualizar/conversa/<int:conversa_id>')
def visualizar_conversa(conversa_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    return render_template('visualizar_conversa.html', conversa_id=conversa_id)

@admin_routes_bp.route('/api/conversas/<int:conversa_id>')
def obter_conversa(conversa_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        conversa_base = supabase.table("conversas") \
            .select("""
                *,
                usuarios: usuarios!inner (
                    nome
                ),
                ai_models: ai_models!inner (
                    nome,
                    empresa
                )
            """) \
            .eq("id", conversa_id) \
            .single() \
            .execute()

        if not conversa_base.data:
            return jsonify({'error': 'Conversa não encontrada'}), 404

        conversa = conversa_base.data

        mensagens = supabase.table("mensagens") \
            .select("""
                *,
                feedback: feedback!left (
                    tipo,
                    comentario,
                    data_feedback
                ),
                token_metrics: token_metrics!left (
                    input_tokens,
                    output_tokens
                )
            """) \
            .eq("id_conversa", conversa_id) \
            .order("data_hora_envio") \
            .execute()

        mensagens_formatadas = []
        total_input_tokens = 0
        total_output_tokens = 0

        for msg in mensagens.data:
            token_data = msg.get('token_metrics', [{}])[0] if msg.get('token_metrics') else {}
            input_tokens = token_data.get('input_tokens', 0)
            output_tokens = token_data.get('output_tokens', 0)

            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

            feedback = msg.get('feedback', [{}])[0] if msg.get('feedback') else {}

            mensagens_formatadas.append({
                'role': 'user',
                'content': msg['texto_usuario'],
                'timestamp': msg['data_hora_envio']
            })

            mensagens_formatadas.append({
                'role': 'assistant',
                'content': msg['texto_gpt'],
                'timestamp': msg['data_hora_envio'],
                'feedback_tipo': feedback.get('tipo'),
                'feedback_comentario': feedback.get('comentario'),
                'feedback_data': feedback.get('data_feedback'),
                'tokens': {
                    'input': input_tokens,
                    'output': output_tokens
                }
            })

        usuario_nome = conversa.get('usuarios', [{}])[0].get('nome', 'Usuário Desconhecido')
        modelo_info = conversa.get('ai_models', [{}])[0] if conversa.get('ai_models') else {}

        return jsonify({
            'id': conversa_id,
            'data_inicio': conversa['data_inicio'],
            'usuario': {
                'nome': usuario_nome
            },
            'modelo': {
                'nome': modelo_info.get('nome', 'Modelo Desconhecido'),
                'empresa': modelo_info.get('empresa', '')
            },
            'messages': mensagens_formatadas,
            'metricas': {
                'total_input_tokens': total_input_tokens,
                'total_output_tokens': total_output_tokens,
                'total_tokens': total_input_tokens + total_output_tokens
            }
        })

    except Exception as e:
        print(f"Erro ao carregar conversa {conversa_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@admin_routes_bp.route('/assistentes')
def gerenciar_assistentes():
    print("\n=== Página de Gerenciamento de Assistentes ===")

    if not session.get('is_admin'):
        print("Erro: Usuário não é admin")
        return redirect(url_for('login'))

    try:
        print("Buscando assistentes no banco...")
        response = supabase.table("ai_models").select("*").execute()
        assistants = response.data
        print(f"Encontrados {len(assistants)} assistentes")

        return render_template('gerenciar_assistentes.html', assistants=assistants)
    except Exception as e:
        print(f"Erro ao carregar página: {str(e)}")
        return render_template('gerenciar_assistentes.html', assistants=[], error=str(e))


temp_file_storage = {}


@admin_routes_bp.route('/api/assistants/upload-file', methods=['POST'])
def upload_file():
    print("\n=== Iniciando upload de arquivo ===")

    if not session.get('is_admin'):
        print("Erro: Usuário não é admin")
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        print("Verificando arquivo no request...")
        if 'file' not in request.files:
            print("Erro: Nenhum arquivo encontrado no request")
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400

        file = request.files['file']
        print(f"Arquivo recebido: {file.filename}")

        if not file.filename:
            print("Erro: Nome do arquivo vazio")
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400

        print("Obtendo API key do usuário...")
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            print(f"Erro: API key não encontrada para usuário {session['usuario_id']}")
            return jsonify({'error': 'API key não configurada'}), 400

        print("Inicializando cliente OpenAI...")
        client = OpenAI(api_key=api_key)

        # Upload do arquivo - convertendo FileStorage para bytes
        print("Iniciando upload do arquivo para OpenAI...")
        try:
            # Lê o conteúdo do arquivo como bytes
            file_content = file.read()

            file_response = client.files.create(
                file=(file.filename, file_content, file.content_type),
                purpose='assistants'
            )
            print(f"Arquivo enviado com sucesso. File ID: {file_response.id}")

            # Armazenar o file_id
            session_id = session['usuario_id']
            if session_id not in temp_file_storage:
                temp_file_storage[session_id] = []
            temp_file_storage[session_id].append(file_response.id)

            return jsonify({
                'file_id': file_response.id,
                'filename': file.filename
            })

        except Exception as e:
            print(f"Erro no upload do arquivo: {e}")
            raise

    except Exception as e:
        print(f"Erro geral no upload: {e}")
        return jsonify({'error': str(e)}), 500

# admin_routes.py - linha ~470
@admin_routes_bp.route('/api/assistants', methods=['GET', 'POST'])
def manage_assistants():
    print("\n=== Gerenciamento de Assistentes ===")

    if not session.get('is_admin'):
        print("Erro: Usuário não é admin")
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        print("Obtendo API key do usuário...")
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            print(f"Erro: API key não encontrada para usuário {session['usuario_id']}")
            return jsonify({'error': 'API key não configurada'}), 400

        print("Inicializando cliente OpenAI...")
        client = OpenAI(api_key=api_key)

        if request.method == 'POST':
            print("Criando novo assistente...")
            data = request.get_json()
            print(f"Dados recebidos: {data}")

            session_id = session['usuario_id']
            file_ids = temp_file_storage.get(session_id, [])

            # Primeiro, criar o vector store se houver arquivos
            if file_ids:
                try:
                    # Criar vector store
                    vector_store = client.beta.vector_stores.create(
                        name=f"store_{data['name']}"
                    )
                    print(f"Vector store criado: {vector_store.id}")

                    # Adicionar todos os arquivos ao vector store usando batch
                    file_batch = client.beta.vector_stores.file_batches.create_and_poll(
                        vector_store_id=vector_store.id,
                        file_ids=file_ids
                    )
                    print(f"Status do batch: {file_batch.status}")
                    print(f"Contagem de arquivos: {file_batch.file_counts}")

                    tool_resources = {
                        "file_search": {
                            "vector_store_ids": [vector_store.id]
                        }
                    }

                    # Limpar os arquivos temporários após sucesso
                    if session_id in temp_file_storage:
                        del temp_file_storage[session_id]

                except Exception as e:
                    print(f"Erro ao criar/configurar vector store: {e}")
                    # Pode ser uma boa ideia limpar os arquivos em caso de erro também
                    if session_id in temp_file_storage:
                        del temp_file_storage[session_id]
                    raise
            # Preparar ferramentas
            tools = []
            if data.get('tools'):
                print(f"Ferramentas solicitadas: {data['tools']}")
                tools = [{"type": tool} for tool in data['tools']]

            # Adicionar file_search se houver arquivo
            if data.get('file_id'):
                tools.append({"type": "file_search"})

            # Configurar parâmetros do assistente
            assistant_params = {
                "name": data['name'],
                "model": data['model'],
                "instructions": data.get('instructions', ''),
                "tools": tools
            }

            if data.get('description'):
                assistant_params["description"] = data['description']

            if 'tool_resources' in locals():
                assistant_params["tool_resources"] = tool_resources

            print(f"Parâmetros do assistente: {assistant_params}")

            try:
                print("Criando assistente na OpenAI...")
                assistant = client.beta.assistants.create(**assistant_params)
                print(f"Assistente criado com ID: {assistant.id}")

                # Salvar no banco
                print("Salvando no banco de dados...")
                assistant_data = {
                    "nome": data['name'],
                    "modelo": data['model'],
                    "empresa": "OpenAI",
                    "assistant_id": assistant.id,
                    "created_at": datetime.now().isoformat()
                }

                response = supabase.table("ai_models").insert(assistant_data).execute()
                print(f"Assistente salvo no banco com ID: {response.data[0]['id']}")

                return jsonify(response.data[0])

            except Exception as e:
                print(f"Erro ao criar assistente: {str(e)}")
                # Se der erro ao criar na OpenAI, verifica se o assistente foi criado
                try:
                    if 'assistant' in locals():
                        print(f"Tentando deletar assistente criado na OpenAI: {assistant.id}")
                        client.beta.assistants.delete(assistant.id)
                except:
                    print("Não foi possível deletar o assistente da OpenAI")
                raise

    except Exception as e:
        error_msg = str(e)
        print(f"Erro geral: {error_msg}")
        return jsonify({'error': error_msg}), 500


@admin_routes_bp.route('/api/assistants/<int:assistant_id>', methods=['DELETE'])
def delete_assistant(assistant_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        # Primeiro busca o assistant_id da OpenAI
        assistant = supabase.table("ai_models").select("*").eq("id", assistant_id).single().execute()
        if not assistant.data:
            return jsonify({'error': 'Assistente não encontrado'}), 404

        # Deleta da OpenAI
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            return jsonify({'error': 'API key não configurada'}), 400

        client = OpenAI(api_key=api_key)
        client.beta.assistants.delete(assistant.data['assistant_id'])

        # Deleta do banco
        supabase.table("ai_models").delete().eq("id", assistant_id).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_routes_bp.route('/api/vector-stores/status/<store_id>')
def check_vector_store_status(store_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        api_key = get_api_key(session['usuario_id'])
        client = OpenAI(api_key=api_key)

        store = client.beta.vector_stores.retrieve(store_id)
        return jsonify({
            'status': store.status,
            'file_counts': store.file_counts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_routes_bp.route('/metricas/uso')
def metricas_uso_usuarios():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # Buscar usuários para referência
    usuarios = supabase.table("usuarios").select("*").execute()
    return render_template('metricas_uso.html', usuarios=usuarios.data)


@admin_routes_bp.route('/api/metricas/uso_usuarios')
def api_metricas_uso_usuarios():
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    try:
        # Usar a view que já existe com as métricas agregadas
        response = supabase.table("vw_user_usage") \
            .select("*") \
            .execute()

        # Buscar tokens do mês atual
        primeiro_dia_mes = datetime.now().replace(day=1).strftime('%Y-%m-%d')

        # Buscar limites dos usuários
        limites = supabase.table("user_limits") \
            .select("usuario_id, limite_tokens_mensal") \
            .execute()

        # Processar os dados
        usuarios_processados = []
        for metrica in response.data:
            usuario_id = metrica.get('usuario_id')


            usuarios_processados.append({
                'usuario_nome': metrica.get('usuario_nome'),
                'total_tokens': metrica.get('total_tokens', 0),
                'total_conversas': metrica.get('total_conversas', 0),
                'total_mensagens': metrica.get('total_mensagens', 0),
                'limite_tokens': metrica.get('limite_tokens', 0),
                'percentual_uso': metrica.get('percentual_uso', 0)
            })

        return jsonify({
            'metricas_gerais': usuarios_processados
        })

    except Exception as e:
        print(f"Erro ao buscar métricas: {e}")
        return jsonify({'error': str(e)}), 500
from flask import Blueprint, render_template, jsonify, session, request, redirect, url_for
from api.database import db, Usuario, Conversa, Mensagem
import bcrypt
from api.supabase_client import supabase
from datetime import datetime, timedelta
from collections import defaultdict

admin_routes_bp = Blueprint('admin_routes', __name__)

# Dashboard
@admin_routes_bp.route('/dashboard')
def dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # Buscar usuários para o filtro
    usuarios = []
    try:
        response = supabase.table("usuarios").select("id, nome").execute()
        usuarios = response.data
    except Exception as e:
        print(f"Erro ao buscar usuários: {e}")

    return render_template('dashboard.html', usuarios=usuarios)

@admin_routes_bp.route('/metricas/tokens/usuarios', methods=['GET'])
def obter_metricas_tokens_usuarios():
    if not session.get('is_admin'):
        return jsonify({'error': 'Acesso negado'}), 403

    # Obtém parâmetros de filtro
    dias = request.args.get('dias', default=30, type=int)
    usuario_id = request.args.get('usuario_id', type=int)

    try:
        # Constrói a query base
        query = supabase.table("token_metrics") \
            .select("*, usuarios(nome)") \
            .gte('timestamp', (datetime.now() - timedelta(days=dias)).isoformat())

        # Adiciona filtro por usuário se especificado
        if usuario_id:
            query = query.eq('usuario_id', usuario_id)

        response = query.execute()

        # Processa os dados
        usuarios_metricas = defaultdict(lambda: {
            'nome': '',
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'metricas_diarias': defaultdict(lambda: {'input': 0, 'output': 0})
        })

        for metric in response.data:
            usuario_id = metric['usuario_id']
            usuarios_metricas[usuario_id]['nome'] = metric['usuarios']['nome']
            usuarios_metricas[usuario_id]['total_input_tokens'] += metric['input_tokens']
            usuarios_metricas[usuario_id]['total_output_tokens'] += metric['output_tokens']

            # Agrupa por dia
            dia = datetime.fromisoformat(metric['timestamp']).strftime('%Y-%m-%d')
            usuarios_metricas[usuario_id]['metricas_diarias'][dia]['input'] += metric['input_tokens']
            usuarios_metricas[usuario_id]['metricas_diarias'][dia]['output'] += metric['output_tokens']

        return jsonify({
            'usuarios': dict(usuarios_metricas),
            'periodo_dias': dias
        })

    except Exception as e:
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

        # Criptografa a senha e adiciona o novo usuário
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

    conversas = Conversa.query.join(Usuario).all()  # Inclui o relacionamento com o usuário
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
        usuario_nome=conversa.usuario.nome  # Passa o nome do usuário
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

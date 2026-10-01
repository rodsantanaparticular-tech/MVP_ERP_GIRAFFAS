"""Registra todos os modelos no Base.metadata (usado por Alembic e pela API)."""
from core.audit import AuditLog  # noqa: F401
from modules.identity.models import PapelAcesso, PapelPermissao, Permissao, Usuario, UsuarioLoja, UsuarioPapel  # noqa: F401
from modules.integrations.models import Conexao, Credencial, CredencialAcesso, Integracao, TenantChave  # noqa: F401
from modules.ops.models import RpaErro  # noqa: F401
from modules.pagamentos.models import DespesaRecorrente, Fornecedor, PadraoPagamento  # noqa: F401
from modules.raiox_dre.models import Auditoria, Despesa, RegraClassificacao, SyncSession  # noqa: F401
from modules.tenants.models import Loja, Rede, Tenant  # noqa: F401
from modules.vendas.models import RealizadoDia  # noqa: F401
from modules.banco.models import ContaBancaria, ExtratoImportacao, ExtratoCategoria, ExtratoLancamento, ExtratoRegra  # noqa: F401

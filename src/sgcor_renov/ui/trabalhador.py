"""Roda o robô numa thread Python própria, que só executa comandos de uma fila.

Por que não um QThread: o Playwright síncrono usa um laço asyncio interno; se o laço de eventos do Qt roda na
mesma thread entre um comando e outro, o 2º comando quebra ("loop is not the running loop") e o app trava.
Aqui a thread do robô fica parada em `queue.get()` entre comandos e nunca devolve o controle ao Qt.

A tela chama verificar()/executar()/encerrar() (enfileiram comandos) e decidir() (Continuar/Pular/Parar/Retomar);
o robô avisa a tela por sinais Qt (entregues na thread da tela).
"""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..caminhos import longo
from ..coberturas import Dicionario
from ..config import Config
from ..estado import Estado, pasta_dados
from ..modelos import Caso
from ..robo.navegador import FalhaRobo, Robo, SessaoExpirada
from ..scanner import dir_cadastrados

log = logging.getLogger("sgcor_renov.robo")
RETENCAO_DIAS = 90   # Q25


def limpar_antigos(raiz: Path, dias: int = RETENCAO_DIAS) -> None:
    """Apaga prints/logs locais com mais de 90 dias (têm dados de clientes)."""
    if not raiz.exists():
        return
    limite = time.time() - dias * 86400
    for p in raiz.iterdir():
        try:
            if p.stat().st_mtime < limite:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError:
            pass


def duracao(segundos: float) -> str:
    """38 s · 1 min 05 s (para o log)."""
    s = round(segundos)
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


def mover_para_cadastrados(pasta: Path) -> Path:
    """Q10/Q21: só depois de tudo gravado. Q85: FECHADOS-X/<lotérica> → _CADASTRADOS/<lotérica>, com a
    _CADASTRADOS na pasta-mãe, ao lado de FECHADOS-PORTO e FECHADOS-TOKIO (criada se não existir)."""
    destino_dir = dir_cadastrados(pasta)
    destino_dir.mkdir(exist_ok=True)
    destino = destino_dir / pasta.name
    if destino.exists():
        destino = destino_dir / f"{pasta.name} ({datetime.now():%Y%m%d-%H%M%S})"
    shutil.move(longo(pasta), longo(destino))
    return destino


class _ParaTela(logging.Handler):
    def __init__(self, sinal):
        super().__init__()
        self.sinal = sinal
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.sinal.emit(self.format(record))


def configurar_log(sinal) -> None:
    pasta = pasta_dados() / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    limpar_antigos(pasta)
    limpar_antigos(pasta_dados() / "prints")
    lg = logging.getLogger("sgcor_renov")
    lg.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in lg.handlers):
        fh = logging.FileHandler(pasta / f"robo-{datetime.now():%Y%m%d}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(fh)
    lg.addHandler(_ParaTela(sinal))


class Trabalhador(QObject):
    linha_log = Signal(str)
    conexao = Signal(bool, object)          # logado, [(id, nome)] produtores
    esperando_login = Signal()
    situacao = Signal(object, str)          # pasta, texto ("Buscando…", "Pulada", "Pendência SGCOR: …")
    aguardando = Signal(object, object)     # Caso, [Campo] — 1ª tela preenchida, esperando o consultor
    login_necessario = Signal()
    pausado = Signal(bool)
    fim_lote = Signal(str)                  # resumo

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.decisoes: queue.Queue[str] = queue.Queue()
        self.comandos: queue.Queue[tuple] = queue.Queue()
        self.pausa = threading.Event()        # setado = pausar ao terminar a lotérica atual (Q47)
        self.parar_lote = threading.Event()   # setado = não começar a próxima lotérica
        self.robo: Robo | None = None
        self._thread = threading.Thread(target=self._laco, name="robo-sgcor", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- chamados da thread da tela

    def pedir_verificacao(self) -> None:
        self.comandos.put(("verificar",))

    def pedir_execucao(self, casos: list[Caso], produtor: str, modo: str = "automatico") -> None:
        self.comandos.put(("executar", casos, produtor, modo))

    def decidir(self, acao: str) -> None:       # "continuar" | "pular" | "parar" | "retomar"
        self.decisoes.put(acao)

    def pedir_parada(self) -> None:
        """Termina a lotérica em andamento e para (nunca interrompe no meio de uma gravação)."""
        self.parar_lote.set()
        self.pausa.clear()
        self.decisoes.put("parar")

    def finalizar(self, espera_s: float = 10) -> None:
        """Fecha o navegador do robô (na thread dele) e encerra a thread."""
        self.decisoes.put("parar")
        self.comandos.put(("sair",))
        self._thread.join(espera_s)

    def _laco(self) -> None:
        while True:
            cmd, *args = self.comandos.get()
            if cmd == "sair":
                self.encerrar()
                return
            try:
                getattr(self, cmd)(*args)
            except Exception as e:   # nunca deixar a thread do robô morrer
                log.error("Erro inesperado no robô (%s): %s", cmd, e)

    # ---------------------------------------------------------------- na thread do robô

    @property
    def estado(self) -> Estado:
        """Conexão própria da thread do robô com o estado local (SQLite não compartilha conexão entre threads)."""
        if getattr(self, "_estado", None) is None:
            self._estado = Estado()
        return self._estado

    def _robo(self) -> Robo:
        if self.robo is None:
            configurar_log(self.linha_log)
            self.robo = Robo(self.cfg, pasta_dados() / "perfil-sgcor", pasta_dados() / "prints")
        return self.robo

    def verificar(self) -> None:
        r = self._robo()
        try:
            def esperando():
                s = self.cfg.espera_login
                prazo = f"{s // 60} min" if s >= 60 else f"{s} s"
                log.info("O SGCOR pediu login: entre com o seu usuário na janela do robô (Chrome). "
                         "Ela conecta sozinha assim que o login terminar (até %s).", prazo)
                self.esperando_login.emit()

            if r.verificar(ao_esperar=esperando):
                prods = r.produtores()
                log.info("Conectado ao SGCOR. %d produtores carregados.", len(prods))
                self.conexao.emit(True, prods)
            else:
                log.info("O login não foi feito a tempo. Clique em Verificar conexão para tentar de novo.")
                self.conexao.emit(False, [])
        except FalhaRobo as e:
            log.error("%s", e)
            self.conexao.emit(False, [])
        except Exception as e:
            log.error("Erro ao verificar a conexão: %s", str(e).splitlines()[0] if str(e) else type(e).__name__)
            r.fechar()          # nunca reaproveitar um navegador em estado desconhecido
            self.conexao.emit(False, [])

    def executar(self, casos: list[Caso], produtor: str, modo: str = "automatico") -> None:
        r = self._robo()
        while not self.decisoes.empty():
            self.decisoes.get_nowait()
        self.parar_lote.clear()
        dic = Dicionario.carregar()
        cadastradas = puladas = pendentes = metade = 0
        inicio_lote = time.monotonic()
        parar = False
        log.info("Lote iniciado: %d lotérica(s), modo %s, produtor %s.", len(casos),
                 "Automático" if modo == "automatico" else "Conferência", produtor)
        for caso in casos:
            if parar or self.parar_lote.is_set():
                break
            if self.pausa.is_set():
                self.pausado.emit(True)
                log.info("Pausado. Clique em Continuar o lote para retomar.")
                while (d := self.decisoes.get()) not in ("retomar", "parar"):
                    pass
                self.pausa.clear()
                self.pausado.emit(False)
                if d == "parar":
                    break
            proposta_id = None    # ID da renovação no SGCOR depois do Avançar
            inicio = time.monotonic()   # tempo de cada cadastro no log
            etapa = "coberturas"
            retomar = self.estado.pela_metade(caso.pasta)
            if retomar:
                # renovação já criada numa execução anterior que parou no meio: continua da etapa, sem criar outra
                proposta_id, etapa = retomar
                log.info("%s: retomando a renovação ID %s a partir da etapa %s.", caso.nome, proposta_id, etapa)
            while True:   # repete a mesma lotérica depois de um novo login
                try:
                    if proposta_id is None:
                        self.situacao.emit(caso.pasta, "Buscando no SGCOR…")
                        linha = r.buscar(caso)
                        self.situacao.emit(caso.pasta, "Preenchendo a 1ª tela…")
                        campos = r.preencher_renovacao(caso, linha)
                        if modo == "conferencia":
                            self.situacao.emit(caso.pasta, "Aguardando sua conferência")
                            self.aguardando.emit(caso, campos)
                            acao = self.decisoes.get()
                            self._registrar_correcoes(caso, campos)
                            if acao != "continuar":
                                r.descartar()
                                self.situacao.emit(caso.pasta, "Pulada — nada gravado")
                                puladas += 1
                                parar = acao == "parar"
                                break
                        self.situacao.emit(caso.pasta, "Avançando (a renovação passa a existir no SGCOR)…")
                        proposta_id = r.avancar(caso)
                        etapa = "coberturas"
                    else:
                        # retomada (login no meio ou execução anterior): segue da etapa, sem criar outra renovação
                        pass
                    if etapa == "coberturas":
                        self.situacao.emit(caso.pasta, f"ID {proposta_id}: coberturas…")
                        r.coberturas(caso, proposta_id, dic)
                        etapa = "repasse"
                    if etapa == "repasse":
                        self.situacao.emit(caso.pasta, f"ID {proposta_id}: repasse…")
                        r.repasse(caso, proposta_id, produtor)
                        etapa = "parcelas"
                    if etapa == "parcelas":
                        self.situacao.emit(caso.pasta, f"ID {proposta_id}: parcelas…")
                        r.parcelas(caso, proposta_id)
                        etapa = "anexos"
                    if etapa == "anexos":
                        self.situacao.emit(caso.pasta, f"ID {proposta_id}: anexos…")
                        r.anexos(caso, proposta_id)
                    self.estado.limpar_pela_metade(caso.pasta)
                    destino = mover_para_cadastrados(caso.pasta)
                    self.estado.registrar_cadastrada(destino, caso.nome, caso.seguradora, proposta_id, produtor)
                    log.info("%s: CADASTRADA no SGCOR (ID %s) em %s. Pasta movida para %s.", caso.nome, proposta_id,
                             duracao(time.monotonic() - inicio), destino.parent.name)
                    self.situacao.emit(caso.pasta, f"Cadastrada no SGCOR (ID {proposta_id})")
                    cadastradas += 1
                    break
                except SessaoExpirada:
                    log.warning("O SGCOR pediu login. Faça o login na janela do robô e clique em Retomar.")
                    self.login_necessario.emit()
                    if self.decisoes.get() == "parar":
                        parar = True
                        break
                except Exception as e:
                    falha = isinstance(e, FalhaRobo)
                    msg = str(e) if falha else f"erro inesperado: {str(e).splitlines()[0] if str(e) else e!r}"
                    if r.page:
                        r.print_(caso, "falha" if falha else "erro")
                    if proposta_id:
                        # Q12: a renovação já existe — não mexe mais agora; fica guardada para retomar desta etapa
                        self.estado.marcar_pela_metade(caso.pasta, proposta_id, etapa, msg)
                        log.warning("%s: PELA METADE (ID %s, etapa %s, após %s): %s — execute de novo para retomar "
                                    "desta etapa, ou termine no SGCOR.", caso.nome, proposta_id, etapa,
                                    duracao(time.monotonic() - inicio), msg)
                        self.situacao.emit(caso.pasta, f"Pela metade (ID {proposta_id}, {etapa}): {msg}")
                        metade += 1
                    else:
                        log.warning("%s: %s", caso.nome, msg)
                        self.situacao.emit(caso.pasta, f"Pendência SGCOR: {msg}")
                        pendentes += 1
                        self._sair_sem_salvar()
                    break
        total = time.monotonic() - inicio_lote
        media = f", média de {duracao(total / cadastradas)} por cadastro" if cadastradas else ""
        resumo = (f"Lote encerrado em {duracao(total)}: {cadastradas} cadastrada(s), {metade} pela metade (terminar "
                  f"no SGCOR), {pendentes} com pendência antes de gravar, {puladas} pulada(s){media}.")
        log.info(resumo)
        self.fim_lote.emit(resumo)

    def _sair_sem_salvar(self) -> None:
        try:
            self.robo.descartar()
        except Exception:
            pass

    def _registrar_correcoes(self, caso: Caso, campos) -> None:
        """Q42: o que o consultor mudou na tela antes de decidir fica no log (para melhorar as regras)."""
        try:
            atuais = self.robo.ler_campos(campos)
        except Exception:
            return
        for c, atual in zip(campos, atuais):
            if atual.strip() != c.valor.strip():
                log.info("%s: consultor alterou “%s”: robô pôs “%s”, ficou “%s”.", caso.nome, c.rotulo, c.valor, atual)

    def encerrar(self) -> None:
        if self.robo:
            try:
                self.robo.fechar()
            except Exception:
                pass

import os, sys, argparse, requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from collections import Counter
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

console = Console()
load_dotenv()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
BASE_URL = "https://api.github.com"

class CustomArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(Panel(
            f"[bold red]Erro nos Argumentos:[/bold red]\n{message}\n\n"
            "[dim]Use [bold cyan]--help[/bold cyan] para ver a lista de argumentos obrigatórios.[/dim]",
            title="[bold red]Parâmetro Ausente ou Inválido[/bold red]",
            border_style="red"
        ))
        sys.exit(2)

def github_request(endpoint, params=None, token=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 404:
            print(Panel("[bold red]Erro 404:[/bold red] Usuário ou recurso não encontrado no GitHub.", border_style="red"))
            return None

        elif response.status_code in (401, 403):
            print(Panel(
                "[bold red]Erro de Autenticação/Limite (401/403):[/bold red]\n"
                "Token inválido ou limite de requisições à API excedido.",
                border_style="red"
            ))
            return None

        elif response.status_code >= 500:
            print(Panel(
                f"[bold red]Erro {response.status_code}:[/bold red] Falha nos servidores do GitHub.",
                border_style="red"
            ))
            return None

        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        print(Panel("[bold red]Erro de Conexão:[/bold red] Timeout na requisição.", border_style="red"))
        return None

    except requests.exceptions.RequestException as err:
        print(Panel(f"[bold red]Falha de Rede:[/bold red] {err}", border_style="red"))
        return None

def fetch_user_events(username, days, token=None):
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    events = []
    page = 1
    per_page = 100

    while True:
        data = github_request(
            f"/users/{username}/events", 
            params={"page": page, "per_page": per_page}, 
            token=token
        )

        if not data:
            break

        stop_pagination = False

        for event in data:
            created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))

            if created_at < cutoff_date:
                stop_pagination = True
                break

            events.append(event)

        if stop_pagination or len(data) < per_page:
            break

        page += 1

    return events

def fetch_user_repos(username, token=None):
    repos = []
    page = 1
    per_page = 100

    while True:
        data = github_request(
            f"/users/{username}/repos", 
            params={"page": page, "per_page": per_page, "type": "public"}, 
            token=token
        )

        if not data:
            break

        repos.extend(data)

        if len(data) < per_page:
            break

        page += 1

    languages = Counter()
    for repo in repos:
        lang = repo.get("language")
        if lang:
            languages[lang] += 1

    return repos, languages

def calculate_event_stats(events):
    total_commits = 0
    prs_opened = 0
    prs_merged = 0
    issues_opened = 0
    outros_eventos = 0

    for event in events:
        event_type = event.get("type")
        payload = event.get("payload", {})

        if event_type == "PushEvent":
            commits = payload.get("commits")
            if commits is not None:
                total_commits += len(commits)
            else:
                total_commits += payload.get("distinct_size", payload.get("size", 1))

        elif event_type == "PullRequestEvent":
            action = payload.get("action")
            pr_data = payload.get("pull_request", {})

            if action == "opened":
                prs_opened += 1
            elif action == "closed" and pr_data.get("merged") is True:
                prs_merged += 1

        elif event_type == "IssuesEvent":
            if payload.get("action") == "opened":
                issues_opened += 1
        else:
            outros_eventos += 1

    return {
        "total_commits": total_commits,
        "prs_opened": prs_opened,
        "prs_merged": prs_merged,
        "issues_opened": issues_opened,
        "outros_eventos": outros_eventos
    }

def get_top_repositories(events, top_n=5):
    repo_counter = Counter()

    for event in events:
        repo_info = event.get("repo", {})
        repo_name = repo_info.get("name")

        if repo_name:
            repo_counter[repo_name] += 1

    return repo_counter.most_common(top_n)

def get_busiest_day(events):
    if not events:
        return None, 0

    day_counter = Counter()

    for event in events:
        created_at = event.get("created_at")

        if created_at:
            date_str = created_at[:10]
            day_counter[date_str] += 1

    busiest_date, count = day_counter.most_common(1)[0]

    return busiest_date, count

def aggregate_languages(repos):
    lang_counter = Counter()

    for repo in repos:
        language = repo.get("language")

        if language:
            lang_counter[language] += 1

    return lang_counter.most_common()

def display_github_wrapped(username, days, repos, events):
    if not events:
        console.print(
            Panel(
                f"[bold yellow]Nenhuma atividade encontrada![/bold yellow]\n\n"
                f"O usuário [cyan]{username}[/cyan] não possui eventos registrados nos últimos [bold]{days} dias[/bold].\n"
                f"[dim]Tente aumentar a janela de tempo usando a flag --days (ex: --days 90).[/dim]",
                title="[bold yellow]Estado Vazio[/bold yellow]",
                border_style="yellow",
                expand=False
            )
        )
        return

    stats = calculate_event_stats(events)
    top_repos = get_top_repositories(events, top_n=5)
    busiest_date, busiest_count = get_busiest_day(events)
    languages = aggregate_languages(repos)

    console.print(
        Panel(
            f"[bold magenta]GITHUB WRAPPED[/bold magenta] — [cyan]@{username}[/cyan]\n"
            f"[dim]Relatório de atividades dos últimos {days} dias[/dim]",
            border_style="magenta",
            expand=False
        )
    )

    stats_content = (
        f"• [bold]Commits:[/bold] [cyan]{stats['total_commits']}[/cyan]\n"
        f"• [bold]PRs Abertos:[/bold] [yellow]{stats['prs_opened']}[/yellow]\n"
        f"• [bold]PRs Mesclados:[/bold] [green]{stats['prs_merged']}[/green]\n"
        f"• [bold]Issues Abertas:[/bold] [red]{stats['issues_opened']}[/red]\n"
        f"• [bold]Outras Ações:[/bold] [dim]{stats['outros_eventos']}[/dim]\n"
    )
    if busiest_date:
        stats_content += f"\n[bold]Dia mais ativo:[/bold]\n[bold red]{busiest_date}[/bold red] ({busiest_count} ações)"

    panel_resumo = Panel(
        stats_content, 
        title="[bold green]Resumo de Atividade[/bold green]", 
        border_style="green",
        expand=True
    )

    table_lang = Table(title="Uso de Linguagens", expand=True)
    table_lang.add_column("Linguagem", style="magenta")
    table_lang.add_column("Repos", justify="right", style="bold green")

    if languages:
        for lang, count in languages:
            table_lang.add_row(lang, str(count))
    else:
        table_lang.add_row("[dim]Nenhuma linguagem detectada[/dim]", "-")

    console.print(Columns([panel_resumo, table_lang]))

    table_repos = Table(title="5 Repositórios Principais (por Eventos)", expand=True)
    table_repos.add_column("#", justify="center", style="bold yellow", width=4)
    table_repos.add_column("Nome do Repositório", style="cyan")
    table_repos.add_column("Contagem de Eventos", justify="right", style="green")

    if top_repos:
        for index, (repo_name, count) in enumerate(top_repos, start=1):
            table_repos.add_row(f"{index}º", repo_name, f"{count} eventos")
    else:
        table_repos.add_row("-", "[dim]Nenhum repositório com eventos no período[/dim]", "0 eventos")

    console.print(table_repos)

def positive_day(value):
    try:
        int_value = int(value)

        if int_value <= 0:
            raise argparse.ArgumentTypeError("O número de dias deve ser maior que zero!")
        
        return int_value
    
    except ValueError:
        raise argparse.ArgumentTypeError("O valor informado deve ser um número inteiro!")

def main():
    parser = CustomArgumentParser(
        description="Ferramenta de linha de comando que gera um relatório no estilo 'GitHub Wrapped'"
    )

    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="Nome do usuário"
    )
    parser.add_argument(
        "--days",
        type=positive_day,
        required=True,
        help="Quantidade de dias (número inteiro)"
    )

    args = parser.parse_args()

    if not GITHUB_TOKEN:
        console.print(
            Panel(
                "[bold red]Erro de Autenticação:[/bold red]\n"
                "A variável de ambiente [yellow]GITHUB_TOKEN[/yellow] não foi encontrada.\n\n",
                title="[bold red]Variável de Ambiente Ausente[/bold red]",
                border_style="red"
            )
        )
        sys.exit(1)

    console.print(
        f"\n[bold yellow]Coletando dados do GitHub para [cyan]{args.username}[/cyan] (últimos {args.days} dias)...[/bold yellow]\n"
    )

    repos_data = fetch_user_repos(args.username, token=GITHUB_TOKEN)
    events = fetch_user_events(args.username, args.days, token=GITHUB_TOKEN)

    if repos_data is None or events is None:
        console.print("[bold red]Não foi possível gerar o relatório devido a um erro nas requisições.[/bold red]")
        sys.exit(1)

    repos, _ = repos_data

    display_github_wrapped(args.username, args.days, repos, events)

if __name__ == "__main__":
    main()
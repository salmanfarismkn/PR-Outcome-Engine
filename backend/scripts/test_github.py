from app.core.config import Settings
from app.github.client import GitHubClient

settings = Settings()

#gh webhook forward --repo=azuzm/event-checker --events=pull_request,push,check_run --url=http://127.0.0.1:8000/webhooks/github --secret=13579246810

def main() -> None:
    with GitHubClient(
        base_url=settings.github_api_url,
        token=settings.github_token,
    ) as client:
        user = client.get_authenticated_user()
        print(user)

        repositories = client.list_repositories()
        print(f"Repositories: {len(repositories)}")

        for repository in repositories:
            print(repository.full_name)

        repositories = client.list_repositories()

        repository = repositories[0]

        print(repository.full_name)

        pull_requests = client.list_pull_requests(
            repository.owner.login,
            repository.name,
        )

        print(f"Total PRs: {len(pull_requests)}")

        for pr in pull_requests:
            print(
                pr.number,
                pr.title,
                pr.state,
            )
        repositories = client.list_repositories()

        repository = repositories[0]

        pull_requests = client.list_pull_requests(
            repository.owner.login,
            repository.name,
        )
        if not pull_requests:
            print("No pull requests found for this repository.")
            return
        pull_request = pull_requests[0]

        commits = client.list_commits(
            repository.owner.login,
            repository.name,
            pull_request.number,
        )

        print(f"Total commits: {len(commits)}")

        for commit in commits:
            print(commit.sha)
            print(commit.commit.message)

        files = client.list_changed_files(
            repository.owner.login,
            repository.name,
            pull_request.number,
        )

        print(len(files))

        for file in files:
            print(file.filename)

        reviews = client.list_reviews(
            owner=repository.owner.login,
            repository=repository.name,
            pull_number=pull_request.number,
        )

        print(f"Total reviews: {len(reviews)}")

        for review in reviews:
            print(
                review.id,
                review.user.login if review.user else None,
                review.state,
            )

        commits = client.list_commits(
            owner=repository.owner.login,
            repository=repository.name,
            pull_number=pull_request.number,
        )

        latest_commit = commits[0]

        check_runs = client.list_check_runs(
            owner=repository.owner.login,
            repository=repository.name,
            ref=latest_commit.sha,
        )

        print(f"Total check runs: {len(check_runs)}")

        for check in check_runs:
            print(
                check.name,
                check.status,
                check.conclusion,
            )



if __name__ == "__main__":
    main()

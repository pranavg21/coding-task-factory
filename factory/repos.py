"""The supplied repositories. Adding a repository is a new entry here, not new code, as long as its
test framework has a stack in factory/stacks.py."""
from __future__ import annotations

REPOS = {
    "click": dict(repo_id="pallets-click", repo_source="https://github.com/pallets/click",
                  pinned_version="08b803cf32ceb2ae6a772c62d5da42757a897d44", language="python", framework="pytest",
                  docker_image="factory/pallets-click:08b803c",
                  test_cmd=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA")),
    "zod": dict(repo_id="colinhacks-zod", repo_source="https://github.com/colinhacks/zod",
                pinned_version="d40c329910436e528d3c26cb1b9179e05abebf05", language="typescript", framework="vitest",
                docker_image="factory/colinhacks-zod:d40c329", test_project="zod",
                test_cmd=("node_modules/.bin/vitest", "run", "--project", "zod", "--reporter=json")),
    "jsoncpp": dict(repo_id="open-source-parsers-jsoncpp", repo_source="https://github.com/open-source-parsers/jsoncpp",
                    pinned_version="93acc7b155048f1a66c43235cc205519f1e7a6ea", language="cpp", framework="jsontest",
                    docker_image="factory/open-source-parsers-jsoncpp:93acc7b",
                    test_cmd=("build-factory/bin/jsoncpp_test", "--test")),
}

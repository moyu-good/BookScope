PYTHON ?= python3
PIP ?= pip3

.PHONY: install dev web test lint build demo report

install: ## 安装后端 + 前端依赖 + NLTK 资源
	$(PIP) install -e ".[dev]"
	$(PYTHON) -m textblob.download_corpora
	cd web && npm install

dev: ## 启动后端开发服务
	uvicorn bookscope.api.app:create_app --factory --reload --port 8000

web: ## 启动前端开发服务
	cd web && npm run dev

test: ## 跑全套测试
	$(PYTHON) -m pytest tests/ -q

lint: ## ruff 检查
	ruff check bookscope tests

build: ## 前端生产构建
	cd web && npm run build

demo: ## 前端 demo 构建
	cd web && npm run build:demo

report: ## 一条命令把书变成结构版 HTML 报告（用法: make report FILE=书.epub OUT=书鉴.html）
	$(PYTHON) -m bookscope.cli report $(FILE) --out $(OUT)

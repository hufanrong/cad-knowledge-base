# ============================================================
# CAD Knowledge Base - Docker image (CPU build)
# ============================================================
FROM python:3.11-slim

# 系统依赖（ezdxf/向量库等需要的编译与运行库）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先安装依赖层（利用 Docker 层缓存，源码改动不触发重装）
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# 拷贝源码（.dockerignore 已排除数据/环境目录）
COPY . .

# 运行时数据目录（挂载卷）
RUN mkdir -p /app/KnowledgeBase

EXPOSE 8000 8501

# 默认启动 REST API；GUI 服务请通过 docker-compose 覆盖 command
CMD ["python", "-m", "src.cli.main", "serve"]

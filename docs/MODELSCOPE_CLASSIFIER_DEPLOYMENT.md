# RumorBuster 微调模型部署与验收

## 作用边界

模型 `congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets` 在 V3 并行阶段对最多三个实质子主张做纯文本三分类。它不读取网页证据，也不能覆盖确定性规则结论。

正式调用使用 `POST /v1/chat`，固定温度为 0，只接受精确的 `Yes`、`No` 或 `Unknown`。项目不会要求这个只接受标签监督的模型生成事实解释。

## GPU 主机

推荐 Linux、NVIDIA 16GB 以上显存、16GB 以上内存和 30GB 以上磁盘。先取得 ModelScope 仓库中的完整文件和权重，再使用仓库已有 Docker/FastAPI 配置构建镜像：

```bash
git lfs install
git clone \
  https://www.modelscope.cn/models/congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets.git \
  rumorbuster-classifier-model
cd rumorbuster-classifier-model

docker build -t rumorbuster-classifier:local .
docker run --gpus all --name rumorbuster-classifier \
  -p 127.0.0.1:8000:8000 \
  rumorbuster-classifier:local
```

若 ModelScope 下载方式或仓库 Dockerfile 后续变化，以仓库实际文件为准。构建前确认权重分片不是 Git LFS 指针文件。验收时先在 GPU 主机执行：

```bash
curl -fsS http://127.0.0.1:8000/health
```

响应必须表明模型已加载，并在 GPU 环境中显示 CUDA。不得把 `8000` 端口开放到公网安全组。

## SSH 隧道

在运行 RumorBuster 的机器建立隧道：

```bash
ssh -N -L 127.0.0.1:18000:127.0.0.1:8000 USER@GPU_HOST
```

RumorBuster 容器通过 `http://host.docker.internal:18000` 访问该隧道。生产 Compose 已加入 Linux 所需的 `host-gateway` 映射。

`.env.production` 使用：

```dotenv
RUMOR_MODEL_BASE_URL=http://host.docker.internal:18000
RUMOR_MODEL_API_STYLE=modelscope_chat
RUMOR_MODEL_NAME=congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets
RUMOR_MODEL_TIMEOUT_SECONDS=20
RUMOR_CLASSIFIER_REQUIRED=true
```

## 手工请求

```bash
curl -sS http://127.0.0.1:18000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {
        "role": "system",
        "content": "You are a professional rumor detection assistant. Determine whether the following text is a rumor. You must strictly output only one of the following options: '\''Yes'\'', '\''No'\'', or '\''Unknown'\''. If there is not enough information to verify the claim, output '\''Unknown'\''."
      },
      {"role": "user", "content": "待分类子主张"}
    ],
    "max_new_tokens": 8,
    "temperature": 0,
    "top_p": 1,
    "top_k": 20,
    "repetition_penalty": 1
  }'
```

## 课程验收

1. 运行 3 条 Yes、3 条 No、3 条 Unknown 冒烟用例，同一输入各运行两次：

   ```bash
   python3 scripts/run_classifier_smoke.py \
     --base-url http://127.0.0.1:18000 \
     --repeats 2
   ```

   `evaluation/model_smoke_cases.json` 是新增的部署冒烟 Fixture，不属于训练集、原测试集或既有 Benchmark；不得用它宣传泛化准确率。

2. 保存原始响应、标签映射、耗时和失败状态；不得用 Mock 结果代替。
3. 接通 V3 后运行普通事实、专业主张、浏览器划词或 URL 输入各两次。
4. 断开隧道，确认报告显示 `classifier_unavailable`，规则裁决仍能完成。
5. 恢复隧道，确认新请求产生逐子主张审计记录。
6. 完成评测后停止 GPU 实例，避免继续计费。

真实服务稳定后运行冻结评测集：

```bash
python3 scripts/evaluate_finetuned_classifier.py \
  --base-url http://127.0.0.1:18000 \
  --dataset early

python3 scripts/evaluate_finetuned_classifier.py \
  --base-url http://127.0.0.1:18000 \
  --dataset adversarial
```

本文件只提供部署步骤；没有 GPU 主机和 SSH 地址时，不能声称已完成真实远程模型验收。

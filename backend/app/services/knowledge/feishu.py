"""飞书应用身份读取服务。

只接收飞书文档/Wiki 链接，使用 tenant_access_token 访问已授权给应用的资源。
不使用用户 OAuth，也不把密钥写入日志。
"""

from dataclasses import dataclass
from urllib.parse import urlparse
import re
import httpx


_API = "https://open.feishu.cn/open-apis"


@dataclass
class FeishuDocument:
    title: str
    content: str
    source_url: str


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str):
        if not app_id or not app_secret:
            raise ValueError("请先填写飞书 App ID 与 App Secret")
        self.app_id, self.app_secret = app_id, app_secret

    @staticmethod
    def _validate_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        # 实际共享链接通常为 ``tenant.feishu.cn/docx/...``，不能只允许裸域名。
        # 使用域名后缀判断而不是宽泛的子串判断，避免开放重定向/SSRF 入口。
        is_feishu_host = hostname == "feishu.cn" or hostname.endswith(".feishu.cn")
        is_lark_host = hostname == "larksuite.com" or hostname.endswith(".larksuite.com")
        if parsed.scheme != "https" or not (is_feishu_host or is_lark_host):
            raise ValueError("仅支持 https://feishu.cn 或 larksuite.com 的文档链接")
        match = re.search(r"/(docx|wiki)/([A-Za-z0-9]+)", parsed.path)
        if not match:
            raise ValueError("请输入飞书 Docx 或 Wiki 节点链接")
        return match.group(1), match.group(2)

    async def _token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(f"{_API}/auth/v3/tenant_access_token/internal", json={
            "app_id": self.app_id, "app_secret": self.app_secret,
        })
        payload = response.json()
        if response.is_error or payload.get("code", 0) != 0:
            raise RuntimeError(payload.get("msg", "无法获取飞书应用访问令牌"))
        return payload["tenant_access_token"]

    @staticmethod
    async def _get(client: httpx.AsyncClient, path: str, token: str, params: dict | None = None) -> dict:
        response = await client.get(
            f"{_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params,
        )
        payload = response.json()
        if response.is_error or payload.get("code", 0) != 0:
            raise RuntimeError(payload.get("msg", "飞书资源读取失败"))
        return payload.get("data") or {}

    async def test_connection(self) -> None:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            await self._token(client)

    async def import_url(self, url: str, max_nodes: int = 100) -> list[FeishuDocument]:
        kind, token = self._validate_url(url)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            access_token = await self._token(client)
            if kind == "docx":
                return [await self._read_docx(client, access_token, token, url)]
            return await self._read_wiki(client, access_token, token, url, max_nodes)

    async def _read_docx(self, client, token: str, doc_token: str, source_url: str) -> FeishuDocument:
        data = await self._get(client, f"/docx/v1/documents/{doc_token}/raw_content", token)
        content = (data.get("content") or "").strip()
        if not content:
            raise RuntimeError("飞书文档为空，或应用没有正文读取权限")
        title = (data.get("title") or f"飞书文档-{doc_token}").strip()
        return FeishuDocument(title=title, content=content, source_url=source_url)

    async def _read_wiki(self, client, token: str, node_token: str, source_url: str, max_nodes: int) -> list[FeishuDocument]:
        root = await self._get(client, f"/wiki/v2/spaces/get_node?token={node_token}", token)
        node = root.get("node") or {}
        space_id = node.get("space_id")
        if not space_id:
            raise RuntimeError("无法解析飞书知识库节点")
        output: list[FeishuDocument] = []
        queue, visited = [node], set()
        while queue:
            current = queue.pop(0)
            current_token = current.get("node_token")
            if not current_token or current_token in visited:
                continue
            visited.add(current_token)
            if len(visited) > max_nodes:
                raise RuntimeError(f"知识库节点超过导入上限（{max_nodes}）")
            if current.get("obj_type") == "docx" and current.get("obj_token"):
                doc = await self._read_docx(client, token, current["obj_token"], source_url)
                doc.title = current.get("title") or doc.title
                output.append(doc)
            # Wiki 节点列表是分页接口；不处理 page_token 会悄悄漏掉第 51 个之后的同级节点。
            page_token = None
            while True:
                params = {"parent_node_token": current_token, "page_size": 50}
                if page_token:
                    params["page_token"] = page_token
                children = await self._get(client, f"/wiki/v2/spaces/{space_id}/nodes", token, params)
                queue.extend(children.get("items") or [])
                if not children.get("has_more"):
                    break
                page_token = children.get("page_token")
                if not page_token:
                    raise RuntimeError("飞书知识库分页响应缺少 page_token")
        if not output:
            raise RuntimeError("知识库中没有可读取的 Docx 文档，请检查应用权限")
        return output

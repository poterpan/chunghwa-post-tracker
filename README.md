# 📦 中華郵政包裹追蹤器

自動追蹤中華郵政包裹狀態，有新進度時透過 [Bark](https://github.com/Finb/Bark) 推播通知到 iPhone。

透過 GitHub Actions 每 2 小時自動執行，使用 [ddddocr](https://github.com/sml2h3/ddddocr) 自動辨識驗證碼。

## 支援類型

| 類型 | TxnCode | 驗證碼 | 適用 |
|------|---------|--------|------|
| 國內郵件 | EB500100 | 不需要 | 掛號信、包裹等國內郵件 |
| 國際/兩岸e小包 | EB500200 | 自動辨識 | 兩岸e小包、國際包裹 |

## 使用方式

### 1. Fork 此 repo

### 2. 設定 GitHub Secrets

到 repo 的 **Settings → Secrets and variables → Actions** 新增：

| Secret | 說明 | 範例 |
|--------|------|------|
| `BARK_KEY` | Bark 推播 key | `xxxxxxxxxxxxxxxx` |
| `MAIL_NO` | 追蹤單號（支援多筆，逗號分隔） | 見下方格式 |

### 3. MAIL_NO 格式

```bash
# 單筆（自動判斷類型）
MAIL_NO=LH038196094TW

# 多筆（逗號分隔，自動判斷類型）
MAIL_NO=LH038196094TW,94936910008210105002

# 手動指定類型
MAIL_NO=EB500200:LH038196094TW,EB500100:94936910008210105002
```

**自動判斷規則：** 13 碼且開頭為 `E`/`R`/`L`/`C`/`F` 的單號自動判定為國際郵件（EB500200），其餘視為國內郵件（EB500100）。不確定時可用 `EB500200:單號` 手動指定。

### 4. 啟用 GitHub Actions

Fork 後到 **Actions** 頁面啟用 workflows，也可以點 **Run workflow** 手動執行測試。

## 本地執行

```bash
pip install -r requirements.txt
BARK_KEY=your_key MAIL_NO=LH038196094TW python tracker.py
```

## 運作原理

1. GitHub Actions 每 2 小時觸發
2. 查詢中華郵政 API（EB500200 自動用 ddddocr 破解驗證碼）
3. 比對 `status.json` 中的上次紀錄
4. 有新進度 → 透過 Bark 推播通知，並 commit 更新 `status.json`

## 致謝

- 靈感來自 [tonytonyjan/chunghwa_post](https://gist.github.com/tonytonyjan/fe0848997a038ca84081d4664a1f519f)
- 驗證碼辨識：[ddddocr](https://github.com/sml2h3/ddddocr)
- 推播通知：[Bark](https://github.com/Finb/Bark)

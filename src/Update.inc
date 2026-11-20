// ------------------------------------------------------------------ update check
// Optional, asynchronous GitHub Releases check.
//
// Design constraints:
//   * winhttp.dll is loaded at RUN TIME, so the exe keeps its original
//     5-DLL static import table (kernel32/user32/gdi32/comdlg32/shell32).
//   * The request runs on a background thread. Startup is never blocked.
//   * ANY failure (missing DLL, no network, DNS/proxy error, 404 because no
//     release exists yet, rate limit, malformed JSON) ends in UPD_FAILED and
//     is completely silent: no message box, no red dot, no UI change.
//   * Only one GET to api.github.com; no file content is ever uploaded.
#include <process.h>

static const wchar_t* kUpdateApiHost = L"api.github.com";
static const wchar_t* kUpdateApiPath = L"/repos/yutils/BatFix/releases/latest";
static const wchar_t* kUpdatePage    = L"https://github.com/yutils/BatFix/releases/latest";
static const UINT WM_APP_UPDATE_RESULT = WM_APP + 17;

enum { UPD_IDLE = 0, UPD_CHECKING = 1, UPD_LATEST = 2, UPD_AVAILABLE = 3, UPD_FAILED = 4 };
static volatile LONG g_updState = UPD_IDLE;
static volatile LONG g_updBusy  = 0;
static wchar_t g_newVer[64]  = L"";
static wchar_t g_newUrl[512] = L"";
// Developer/test hook only: when non-empty, FetchLatest reads this local
// JSON file instead of calling GitHub. Never used in a normal double-click.
static W g_updateFile;

static int UpdateState() { return (int)InterlockedCompareExchange(&g_updState, 0, 0); }
static void CopyPod(wchar_t* dst, size_t cap, const W& s) {
    size_t n = s.size() < cap - 1 ? s.size() : cap - 1;
    if (n) wmemcpy(dst, s.c_str(), n);
    dst[n] = 0;
}

// ------------------------------------------------------------------ semver-ish
// Accepts "0.0.2", "v0.0.2", "V2.0", "Release 1.2.3", "0.0.2-beta1".
// Numeric parts are compared first; a trailing suffix is a prerelease, so
// 0.0.2-beta1 never counts as newer than the final 0.0.2.
struct Ver {
    int n[4]; bool pre; bool valid;
    Ver() : n{ 0, 0, 0, 0 }, pre(false), valid(false) {}
};
static Ver ParseVer(const W& s) {
    Ver v;
    size_t i = 0;
    while (i < s.size() && (s[i] < L'0' || s[i] > L'9')) ++i;   // skip "v", "Release ", ...
    if (i >= s.size()) return v;
    int k = 0;
    while (i < s.size() && k < 4) {
        int num = 0;
        while (i < s.size() && s[i] >= L'0' && s[i] <= L'9') {
            num = num * 10 + (int)(s[i] - L'0');
            if (num > 999999) num = 999999;                       // overflow guard
            ++i;
        }
        v.n[k++] = num;
        if (i + 1 < s.size() && s[i] == L'.' &&
            s[i + 1] >= L'0' && s[i + 1] <= L'9') { ++i; continue; }
        break;
    }
    v.valid = k > 0;
    if (v.valid) {
        while (i < s.size() && (s[i] == L' ' || s[i] == L'.')) ++i;
        if (i < s.size() && (s[i] < L'0' || s[i] > L'9')) v.pre = true;
    }
    return v;
}
static int CmpVer(const Ver& a, const Ver& b) {
    for (int i = 0; i < 4; ++i)
        if (a.n[i] != b.n[i]) return a.n[i] < b.n[i] ? -1 : 1;
    if (a.pre != b.pre) return a.pre ? -1 : 1;                  // final > prerelease
    return 0;
}
// Shared by the background thread and the offline self-test.
static int ClassifyVersion(const W& localText, const W& remoteText) {
    Ver l = ParseVer(localText), r = ParseVer(remoteText);
    if (!l.valid || !r.valid) return UPD_FAILED;
    return CmpVer(r, l) > 0 ? UPD_AVAILABLE : UPD_LATEST;
}
static W DisplayVer(const wchar_t* v) {
    W s = v ? W(v) : W();
    if (!s.empty() && (s[0] == L'v' || s[0] == L'V')) return s;
    return L"v" + s;
}

// ------------------------------------------------------------------ tiny JSON reader
// No JSON library: we only need three top-level string fields. GitHub emits
// them before "body" / "assets", so the first key match is the right one.
static bool JsonStr(const W& j, const wchar_t* key, W& out) {
    out.clear();
    W pat = L"\""; pat += key; pat += L"\"";
    size_t p = j.find(pat);
    if (p == W::npos) return false;
    p += pat.size();
    auto ws = [](wchar_t c) { return c == L' ' || c == L'\t' || c == L'\r' || c == L'\n'; };
    while (p < j.size() && ws(j[p])) ++p;
    if (p >= j.size() || j[p] != L':') return false;
    ++p;
    while (p < j.size() && ws(j[p])) ++p;
    if (p >= j.size() || j[p] != L'"') return false;
    ++p;
    while (p < j.size() && j[p] != L'"') {
        if (j[p] == L'\\' && p + 1 < j.size()) {
            wchar_t e = j[++p];
            if (e == L'n') out += L'\n';
            else if (e == L't') out += L'\t';
            else if (e == L'u' && p + 4 < j.size()) {
                int cp = 0; bool good = true;
                for (int k = 0; k < 4; ++k) {
                    wchar_t h = j[p + 1 + k];
                    int d = (h >= L'0' && h <= L'9') ? (int)(h - L'0') :
                            (h >= L'a' && h <= L'f') ? (int)(h - L'a') + 10 :
                            (h >= L'A' && h <= L'F') ? (int)(h - L'A') + 10 : -1;
                    if (d < 0) { good = false; break; }
                    cp = cp * 16 + d;
                }
                if (good) { out += (wchar_t)cp; p += 4; } else out += L'?';
            } else out += e;
        } else out += j[p];
        ++p;
    }
    return true;
}
// tag_name is authoritative (the user's tags are "0.0.1"); the release title
// ("v0.0.1") is a fallback. If they disagree, the larger version wins so a
// mistyped tag can never hide a real release.
static bool ParseReleaseJson(const W& j, W& ver, W& url) {
    W tag, name, html;
    bool ht = JsonStr(j, L"tag_name", tag);
    bool hn = JsonStr(j, L"name", name);
    url = kUpdatePage;
    if (JsonStr(j, L"html_url", html) && html.size() < 400 &&
        html.find(L"https://github.com/yutils/BatFix/") == 0) url = html;
    Ver vt = ParseVer(tag), vn = ParseVer(name);
    if (ht && vt.valid && (!vn.valid || CmpVer(vn, vt) <= 0)) { ver = tag; return true; }
    if (hn && vn.valid) { ver = name; return true; }
    if (ht && vt.valid) { ver = tag; return true; }
    return false;
}

// ------------------------------------------------------------------ WinHTTP (dynamic)
typedef void* WH;
typedef WH   (WINAPI *P_Open)(LPCWSTR, DWORD, LPCWSTR, LPCWSTR, DWORD);
typedef BOOL (WINAPI *P_Close)(WH);
typedef BOOL (WINAPI *P_Timeouts)(WH, int, int, int, int);
typedef WH   (WINAPI *P_Connect)(WH, LPCWSTR, WORD, DWORD);
typedef WH   (WINAPI *P_OpenReq)(WH, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR*, DWORD);
typedef BOOL (WINAPI *P_AddHdr)(WH, LPCWSTR, DWORD, DWORD);
typedef BOOL (WINAPI *P_Send)(WH, LPCWSTR, DWORD, LPVOID, DWORD, DWORD, DWORD_PTR);
typedef BOOL (WINAPI *P_Recv)(WH, LPVOID);
typedef BOOL (WINAPI *P_Avail)(WH, LPDWORD);
typedef BOOL (WINAPI *P_Read)(WH, LPVOID, DWORD, LPDWORD);
typedef BOOL (WINAPI *P_QueryHdr)(WH, DWORD, LPCWSTR, LPVOID, LPDWORD, LPDWORD);

static bool FetchLatest(W& ver, W& url) {
    if (!g_updateFile.empty()) {
        // Offline end-to-end test: the rest of the pipeline (JSON parse,
        // version compare, state publish, red dot) is the real one.
        Bytes raw; W err;
        if (!ReadAll(g_updateFile, raw, err)) return false;
        W json;
        if (!Utf8ToWide(raw.data(), (int)raw.size(), json, false)) return false;
        return ParseReleaseJson(json, ver, url);
    }
    HMODULE mod = LoadLibraryW(L"winhttp.dll");
    if (!mod) return false;                       // e.g. stripped-down system
    struct Api {
        P_Open open; P_Close close; P_Timeouts timeouts; P_Connect connect;
        P_OpenReq openReq; P_AddHdr addHdr; P_Send send; P_Recv recv;
        P_Avail avail; P_Read read; P_QueryHdr queryHdr;
    } a = {};
    a.open      = (P_Open)    GetProcAddress(mod, "WinHttpOpen");
    a.close     = (P_Close)   GetProcAddress(mod, "WinHttpCloseHandle");
    a.timeouts  = (P_Timeouts)GetProcAddress(mod, "WinHttpSetTimeouts");
    a.connect   = (P_Connect) GetProcAddress(mod, "WinHttpConnect");
    a.openReq   = (P_OpenReq) GetProcAddress(mod, "WinHttpOpenRequest");
    a.addHdr    = (P_AddHdr)  GetProcAddress(mod, "WinHttpAddRequestHeaders");
    a.send      = (P_Send)    GetProcAddress(mod, "WinHttpSendRequest");
    a.recv      = (P_Recv)    GetProcAddress(mod, "WinHttpReceiveResponse");
    a.avail     = (P_Avail)   GetProcAddress(mod, "WinHttpQueryDataAvailable");
    a.read      = (P_Read)    GetProcAddress(mod, "WinHttpReadData");
    a.queryHdr  = (P_QueryHdr)GetProcAddress(mod, "WinHttpQueryHeaders");
    if (!a.open || !a.close || !a.timeouts || !a.connect || !a.openReq ||
        !a.addHdr || !a.send || !a.recv || !a.avail || !a.read || !a.queryHdr) {
        FreeLibrary(mod); return false;
    }

    const DWORD kProxyAuto = 4, kProxyDefault = 0;   // AUTOMATIC_PROXY / DEFAULT_PROXY
    const DWORD kFlagSecure = 0x00800000;            // WINHTTP_FLAG_SECURE
    const DWORD kAddreqAdd = 0x10000000;             // WINHTTP_ADDREQ_FLAG_ADD
    const DWORD kStatusNumber = 18 | 0x20000000;     // STATUS_CODE | FLAG_NUMBER

    W agent = L"BatFix/" + W(BATFIX_VERSION_WTEXT) + L" (+https://github.com/yutils/BatFix)";
    WH s = a.open(agent.c_str(), kProxyAuto, nullptr, nullptr, 0);
    if (!s) s = a.open(agent.c_str(), kProxyDefault, nullptr, nullptr, 0);
    bool ok = false;
    if (s) {
        a.timeouts(s, 2500, 2500, 3000, 4000);       // bounded, async anyway
        WH c = a.connect(s, kUpdateApiHost, (WORD)443, 0);
        if (c) {
            WH q = a.openReq(c, L"GET", kUpdateApiPath, nullptr, nullptr,
                             nullptr, kFlagSecure);
            if (q) {
                W hdr = L"User-Agent: " + agent + L"\r\nAccept: application/vnd.github+json\r\n";
                if (a.addHdr(q, hdr.c_str(), (DWORD)-1, kAddreqAdd) &&
                    a.send(q, nullptr, 0, nullptr, 0, 0, 0) &&
                    a.recv(q, nullptr)) {
                    DWORD code = 0, sz = sizeof(code);
                    if (a.queryHdr(q, kStatusNumber, nullptr, &code, &sz, nullptr) &&
                        code == 200) {
                        Bytes body;
                        bool readOk = true;
                        for (;;) {
                            DWORD avail = 0;
                            if (!a.avail(q, &avail)) { readOk = false; break; }
                            if (!avail) break;
                            if (body.size() + avail > 262144)
                                avail = (DWORD)(262144 - body.size());
                            if (!avail) break;
                            std::vector<char> tmp((size_t)avail);
                            DWORD got = 0;
                            if (!a.read(q, tmp.data(), avail, &got) || !got) {
                                readOk = false; break;
                            }
                            body.append(tmp.data(), got);
                        }
                        W json;
                        if (readOk && !body.empty() &&
                            Utf8ToWide(body.data(), (int)body.size(), json, false))
                            ok = ParseReleaseJson(json, ver, url);
                    }
                }
                a.close(q);
            }
            a.close(c);
        }
        a.close(s);
    }
    FreeLibrary(mod);
    return ok;
}

// ------------------------------------------------------------------ async driver
static unsigned __stdcall UpdateThread(void* arg) {
    HWND hwnd = (HWND)arg;
    W ver, url;
    int st = UPD_FAILED;
    if (FetchLatest(ver, url)) {
        st = ClassifyVersion(W(BATFIX_VERSION_WTEXT), ver);
        if (st == UPD_AVAILABLE) {
            CopyPod(g_newVer, 64, ver);
            CopyPod(g_newUrl, 512, url);
        }
    }
    if (st != UPD_AVAILABLE) { g_newVer[0] = 0; g_newUrl[0] = 0; }
    InterlockedExchange(&g_updState, st);           // publish (full barrier)
    InterlockedExchange(&g_updBusy, 0);
    if (hwnd && IsWindow(hwnd))
        PostMessageW(hwnd, WM_APP_UPDATE_RESULT, (WPARAM)st, 0);
    return 0;
}
static void StartUpdateCheck(HWND hwnd) {
    if (InterlockedCompareExchange(&g_updBusy, 1, 0) != 0) return;  // one at a time
    InterlockedExchange(&g_updState, UPD_CHECKING);
    uintptr_t h = _beginthreadex(nullptr, 0, UpdateThread, (void*)hwnd, 0, nullptr);
    if (h) CloseHandle((HANDLE)h);
    else {
        InterlockedExchange(&g_updState, UPD_FAILED);
        InterlockedExchange(&g_updBusy, 0);
    }
}

// ------------------------------------------------------------------ diagnostics
// --selftest-update : pure offline logic check (used by tests/test_update.py)
// --update-sync     : one real network probe, prints the state, never shows UI
static int RunUpdateSelfTest() {
    int pass = 0, fail = 0;
    auto ck = [&](bool c, const wchar_t* name) {
        if (c) ++pass;
        else { ++fail; CliWrite(W(L"FAIL ") + name + L"\n"); }
    };
    auto cmp = [](const wchar_t* a, const wchar_t* b) {
        return CmpVer(ParseVer(W(a)), ParseVer(W(b)));
    };
    ck(cmp(L"0.0.2", L"0.0.1") > 0,            L"0.0.2 > 0.0.1");
    ck(cmp(L"v0.0.1", L"0.0.1") == 0,          L"v-prefix is ignored");
    ck(cmp(L"0.1.0", L"0.0.9") > 0,            L"minor beats patch");
    ck(cmp(L"1.0.0", L"0.9.9") > 0,            L"major beats minor");
    ck(cmp(L"0.0.1", L"0.0.2") < 0,            L"older release is not an update");
    ck(cmp(L"V2.0", L"1.9.9") > 0,             L"uppercase V + short version");
    ck(cmp(L"0.0.1-beta1", L"0.0.1") < 0,      L"prerelease < final");
    ck(cmp(L"0.0.1", L"0.0.1-rc1") > 0,        L"final > prerelease");
    ck(cmp(L"v10.20.30.40", L"10.20.30.4") > 0, L"four numeric parts");
    ck(!ParseVer(L"Release").valid,             L"garbage version rejected");
    ck(!ParseVer(L"").valid,                    L"empty version rejected");
    ck(ClassifyVersion(L"0.0.1", L"0.0.2") == UPD_AVAILABLE, L"classify: newer");
    ck(ClassifyVersion(L"0.0.1", L"v0.0.1") == UPD_LATEST,   L"classify: same");
    ck(ClassifyVersion(L"0.0.1", L"0.0.1-beta") == UPD_LATEST, L"classify: prerelease");
    ck(ClassifyVersion(L"0.0.1", L"nonsense") == UPD_FAILED,  L"classify: invalid");

    W ver, url;
    W j = LR"JSON({"url":"https://api.github.com/repos/yutils/BatFix/releases/1",
"html_url":"https://github.com/yutils/BatFix/releases/tag/0.0.2",
"tag_name":"0.0.2","name":"v0.0.2","draft":false,"prerelease":false,
"body":"修复说明：包含 \"tag_name\": \"9.9.9\" 干扰文本\n第二行",
"assets":[{"name":"BatFix_v0.0.2.exe"}]})JSON";
    ck(ParseReleaseJson(j, ver, url),                       L"json: valid release parsed");
    ck(ver == L"0.0.2",                                     L"json: tag_name wins (not 9.9.9 in body)");
    ck(url.find(L"/releases/tag/0.0.2") != W::npos,         L"json: html_url used");
    ck(ClassifyVersion(L"0.0.1", ver) == UPD_AVAILABLE,      L"json: 0.0.2 classified as update");

    ck(ParseReleaseJson(LR"JSON({"name":"v0.0.3"})JSON", ver, url) && ver == L"v0.0.3",
       L"json: name-only fallback");
    ck(ParseReleaseJson(LR"JSON({"tag_name":"0.0.1","name":"v0.0.5"})JSON", ver, url) &&
       ver == L"v0.0.5",                                     L"json: larger of tag/name wins");
    ck(!ParseReleaseJson(LR"JSON({"message":"Not Found"})JSON", ver, url),
       L"json: 404 body rejected");
    ck(!ParseReleaseJson(LR"JSON({"tag_name":"not-a-version"})JSON", ver, url),
       L"json: invalid tag rejected");
    ck(!ParseReleaseJson(L"", ver, url),                     L"json: empty body rejected");
    ck(ParseReleaseJson(LR"JSON({"tag_name":"0.0.2","html_url":"javascript:alert(1)"})JSON", ver, url) &&
       url == W(kUpdatePage),                               L"json: unsafe url falls back");
    W body;
    ck(JsonStr(LR"JSON({"body":"line1\nline2\u4e2d"})JSON", L"body", body) &&
       body.find(L'\n') != W::npos && body.find(L'中') != W::npos,
       L"json: escape sequences decoded");
    ck(DisplayVer(L"0.0.2") == L"v0.0.2" && DisplayVer(L"v0.0.2") == L"v0.0.2",
       L"display version normalised");

    CliWrite(L"UPDATE_SELFTEST pass=" + Itow(pass) + L" fail=" + Itow(fail) + L"\n");
    return fail ? 1 : 0;
}
static int RunUpdateSyncProbe() {
    W ver, url;
    if (FetchLatest(ver, url)) {
        int st = ClassifyVersion(W(BATFIX_VERSION_WTEXT), ver);
        CliWrite(L"UPDATE_SYNC fetch=OK version=" + ver + L" state=" + Itow(st) + L"\n");
        CliWrite(L"  page=" + url + L"\n");
    } else {
        CliWrite(L"UPDATE_SYNC fetch=FAILED state=" + Itow(UPD_FAILED) + L" (silent)\n");
    }
    return 0;                                    // network failure is NOT an app error
}

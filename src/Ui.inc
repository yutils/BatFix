// ------------------------------------------------------------------ modern UI
// Owner-drawn, minimal-text card layout. No child controls, no flicker.
static const wchar_t* kClass = L"BatFix_MainWindow_9C3E";
static const wchar_t* kMutex = L"Local\\BatFix_Singleton_9C3E4A71";

struct Theme {
    COLORREF bg, card, border, text, muted, accent, accent2, accentSoft,
             ok, warn, err, hover, freeBg, freeFg, link;
};
static const Theme kLight = {
    RGB(245,247,251), RGB(255,255,255), RGB(226,232,240), RGB(20,29,45),
    RGB(133,144,162), RGB(47,111,237), RGB(124,77,255), RGB(233,241,255),
    RGB(22,163,74),  RGB(232,163,61), RGB(224,72,72),  RGB(237,242,250),
    RGB(232,247,238), RGB(15,122,58), RGB(37,99,235)
};
static const Theme kDark = {
    RGB(17,21,28),   RGB(27,33,44),   RGB(44,53,67),   RGB(237,241,247),
    RGB(135,146,163), RGB(91,140,255), RGB(168,123,255), RGB(34,48,74),
    RGB(52,211,153), RGB(232,163,61), RGB(240,96,96),  RGB(36,44,57),
    RGB(23,58,44),   RGB(110,231,183), RGB(129,169,255)
};

struct Row { W file, brief, detail; int kind = 0; };
struct Ui {
    HWND hwnd = nullptr;
    int cx = 820, cy = 560;
    double S = 1.0;
    bool dark = false;
    int hover = 0;
    int scroll = 0;
    int pressHit = 0;
    bool check[4] = { true, true, true, false };  // 修复中文 / 备份 / CRLF / 修复乱码
    int cpIdx = 0;
    int done = 0, changed = 0, errors = 0, backed = 0;
    std::vector<Row> rows;
    HICON hAppIcon = nullptr;
    W toastText;
    DWORD toastStart = 0;
    bool toastOn = false, toastPinned = false;   // pinned = screenshot mode
    HFONT fTitle = nullptr, fSub = nullptr, fBody = nullptr,
          fSmall = nullptr, fPill = nullptr, fStat = nullptr, fNum = nullptr;
};
static Ui g_ui;
static const UINT IDT_TOAST = 4711;
static const DWORD kToastLife = 2400;           // ms
// Only a user-initiated check may raise the "already latest" toast. The
// automatic startup check must never interrupt anyone.
static volatile LONG g_toastOnLatest = 0;
static const UINT cps[6] = { 0, 936, 950, 932, 1252, 65001 };
static const wchar_t* cpNames[6] = { L"自动", L"GBK", L"Big5", L"SJIS", L"Latin", L"UTF-8" };
static const wchar_t* cpFull[6] = {
    L"自动检测（系统 ACP）", L"GBK / 936（简体中文）", L"Big5 / 950（繁体中文）",
    L"Shift-JIS / 932（日文）", L"Windows-1252（西欧）", L"UTF-8 / 65001"
};

static int D(int v) { return (int)(v * g_ui.S + 0.5); }
static const Theme& T() { return g_ui.dark ? kDark : kLight; }

static HFONT MakeFont(int px, bool bold) {
    return CreateFontW(-D(px), 0, 0, 0, bold ? FW_SEMIBOLD : FW_NORMAL, 0, 0, 0,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
}
static void RebuildFonts() {
    HFONT old[] = { g_ui.fTitle, g_ui.fSub, g_ui.fBody, g_ui.fSmall,
                    g_ui.fPill, g_ui.fStat, g_ui.fNum };
    for (auto h : old) if (h) DeleteObject(h);
    g_ui.fTitle = MakeFont(27, true);
    g_ui.fSub = MakeFont(13, false);
    g_ui.fBody = MakeFont(15, false);
    g_ui.fSmall = MakeFont(12, false);
    g_ui.fPill = MakeFont(12, false);
    g_ui.fStat = MakeFont(13, false);
    g_ui.fNum = MakeFont(21, true);
}
static RECT R(int x, int y, int w, int h) { RECT r = { x, y, x + w, y + h }; return r; }
static void RoundRect2(HDC dc, RECT r, int rad, COLORREF fill, COLORREF border,
                       int bw = 1, bool dashed = false) {
    HBRUSH br = CreateSolidBrush(fill);
    HPEN pn = CreatePen(dashed ? PS_DASH : PS_SOLID, bw, border);
    HGDIOBJ ob = SelectObject(dc, br), op = SelectObject(dc, pn);
    RoundRect(dc, r.left, r.top, r.right, r.bottom, rad, rad);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(br); DeleteObject(pn);
}
static void Txt(HDC dc, const W& s, RECT r, HFONT f, COLORREF c, UINT fmt) {
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, c);
    HGDIOBJ o = SelectObject(dc, f);
    DrawTextW(dc, s.c_str(), -1, &r, fmt);
    SelectObject(dc, o);
}
static void Line(HDC dc, int x1, int y1, int x2, int y2, COLORREF c, int w = 1) {
    HPEN p = CreatePen(PS_SOLID, w, c);
    HGDIOBJ o = SelectObject(dc, p);
    MoveToEx(dc, x1, y1, nullptr); LineTo(dc, x2, y2);
    SelectObject(dc, o); DeleteObject(p);
}
static COLORREF LerpC(COLORREF a, COLORREF b, double t) {
    if (t < 0) t = 0; if (t > 1) t = 1;
    return RGB((int)(GetRValue(a) + (GetRValue(b) - GetRValue(a)) * t + .5),
               (int)(GetGValue(a) + (GetGValue(b) - GetGValue(a)) * t + .5),
               (int)(GetBValue(a) + (GetBValue(b) - GetBValue(a)) * t + .5));
}
static void GradientH(HDC dc, RECT r, COLORREF c1, COLORREF c2) {
    int w = r.right - r.left;
    for (int x = 0; x < w; ++x) {
        HBRUSH br = CreateSolidBrush(LerpC(c1, c2, w <= 1 ? 0 : (double)x / (w - 1)));
        RECT ln = { r.left + x, r.top, r.left + x + 1, r.bottom };
        FillRect(dc, &ln, br); DeleteObject(br);
    }
}
static void GradientRound(HDC dc, RECT r, int rad, COLORREF c1, COLORREF c2) {
    HRGN rgn = CreateRoundRectRgn(r.left, r.top, r.right + 1, r.bottom + 1, rad, rad);
    int saved = SaveDC(dc);
    SelectClipRgn(dc, rgn);
    int h = r.bottom - r.top;
    for (int y = 0; y < h; ++y) {
        HBRUSH br = CreateSolidBrush(LerpC(c1, c2, h <= 1 ? 0 : (double)y / (h - 1)));
        RECT ln = { r.left, r.top + y, r.right, r.top + y + 1 };
        FillRect(dc, &ln, br); DeleteObject(br);
    }
    RestoreDC(dc, saved);
    DeleteObject(rgn);
}
static void RoundBorder(HDC dc, RECT r, int rad, COLORREF c, int bw = 1) {
    HPEN p = CreatePen(PS_SOLID, bw, c);
    HGDIOBJ op = SelectObject(dc, p);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    RoundRect(dc, r.left, r.top, r.right, r.bottom, rad, rad);
    SelectObject(dc, op); SelectObject(dc, ob);
    DeleteObject(p);
}

// ------------------------------------------------------------------ layout
static RECT BrandIcon()      { return R(D(28), D(12), D(40), D(40)); }
static RECT ThemeRect()      { return R(g_ui.cx - D(28) - D(30), D(16), D(30), D(30)); }
static RECT UpdateRect()     {
    return R(g_ui.cx - D(28) - D(30) - D(10) - D(132), D(16), D(132), D(30));
}
static RECT GithubRect()     { return R(g_ui.cx - D(28) - D(230), D(82), D(230), D(28)); }
static RECT InfoBar()        { return R(D(28), D(76), g_ui.cx - D(56), D(38)); }
static RECT DropRect()       { return R(D(28), D(124), g_ui.cx - D(56), D(112)); }
static RECT StatRect(int i)  {
    return R(D(28) + i * (D(112) + D(10)), D(354), D(112), D(42));
}
static RECT ClearRect()      { return R(g_ui.cx - D(28) - D(44), D(363), D(44), D(24)); }
static RECT ListRect()       { return R(D(28), D(404), g_ui.cx - D(56), g_ui.cy - D(404) - D(16)); }
// Narrow hit area = checkbox + label only. The rest of each column is dead
// space, so brushing past an option can no longer flip it.
static RECT CheckItem(int i) {
    int m = D(28);
    int colW = (g_ui.cx - 2 * m - D(16)) / 2;
    int x = m + (i % 2) * (colW + D(16));
    int y = (i < 2) ? D(246) : D(276);
    return R(x, y, D(172), D(28));
}
static RECT EncodingRect() { return R(D(28), D(312), D(172), D(28)); }
static int VisibleRows() { return ListRect().bottom - ListRect().top <= 0 ? 0 : (ListRect().bottom - ListRect().top) / D(28); }

static int HitTest(int x, int y) {
    auto inside = [&](RECT r) { return x >= r.left && x < r.right && y >= r.top && y < r.bottom; };
    if (inside(ThemeRect())) return 2;
    if (inside(UpdateRect())) return 41;
    if (inside(GithubRect())) return 40;
    if (inside(DropRect())) return 1;
    for (int i = 0; i < 4; ++i) if (inside(CheckItem(i))) return 10 + i;
    if (inside(EncodingRect())) return 14;
    if (inside(ClearRect())) return 20;
    if (inside(ListRect())) return 30;
    return 0;
}

static void ShowEncodingMenu(HWND hwnd) {
    HMENU m = CreatePopupMenu();
    for (int i = 0; i < 6; ++i)
        AppendMenuW(m, MF_STRING | (i == g_ui.cpIdx ? MF_CHECKED : 0), 100 + i, cpFull[i]);
    RECT er = EncodingRect();
    POINT pt = { er.left, er.bottom };
    ClientToScreen(hwnd, &pt);
    int cmd = TrackPopupMenuEx(m, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN,
                               pt.x, pt.y, hwnd, nullptr);
    DestroyMenu(m);
    if (cmd >= 100 && cmd < 106) {
        g_ui.cpIdx = cmd - 100;
        InvalidateRect(hwnd, nullptr, FALSE);
    }
}

// ------------------------------------------------------------------ toast
// A lightweight, non-modal floating card at the bottom centre. It fades in,
// stays for ~2 s, fades out and never steals focus or blocks clicking.
static W LatestToastText() {
    return L"已是最新版  v" + W(BATFIX_VERSION_WTEXT);
}
// Optional diagnostic hook for tests/test_update.py. A normal double-click
// never sets BATFIX_TOAST_TRACE, so this is a complete no-op for users.
static void TraceToast(const W& line) {
    DWORD n = GetEnvironmentVariableW(L"BATFIX_TOAST_TRACE", nullptr, 0);
    if (!n) return;
    W f((size_t)n + 1, L'\0');
    GetEnvironmentVariableW(L"BATFIX_TOAST_TRACE", &f[0], n + 1);
    f.resize(wcslen(f.c_str()));
    if (f.empty()) return;
    HANDLE hf = CreateFileW(f.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr,
                            OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (hf == INVALID_HANDLE_VALUE) return;
    Bytes b; WideToUtf8(line + L"\n", b);
    DWORD wr = 0; WriteFile(hf, b.data(), (DWORD)b.size(), &wr, nullptr);
    CloseHandle(hf);
}
static void ShowToast(HWND hwnd, const W& text) {
    TraceToast(L"TOAST " + text);
    g_ui.toastText = text;
    g_ui.toastStart = GetTickCount();
    g_ui.toastOn = true;
    g_ui.toastPinned = false;
    SetTimer(hwnd, IDT_TOAST, 40, nullptr);
    InvalidateRect(hwnd, nullptr, FALSE);
}
static double ToastAlpha() {
    if (g_ui.toastPinned) return 1.0;
    DWORD e = GetTickCount() - g_ui.toastStart;
    double fi = e < 180 ? (double)e / 180.0 : 1.0;
    double fo = e > 1900 ? 1.0 - (double)(e - 1900) / 500.0 : 1.0;
    double a = fi < fo ? fi : fo;
    return a < 0 ? 0 : a;
}
static void DrawToast(HDC dc, double a) {
    const Theme& t = T();
    int w = D(246), h = D(46);
    RECT tr = R((g_ui.cx - w) / 2, g_ui.cy - h - D(26), w, h);
    COLORREF base = g_ui.dark ? RGB(236, 241, 249) : RGB(28, 34, 46);
    COLORREF fg   = g_ui.dark ? RGB(20, 26, 36)   : RGB(242, 246, 252);
    COLORREF fill = LerpC(t.bg, base, a);
    COLORREF text = LerpC(t.bg, fg, a);
    RoundRect2(dc, tr, D(23), fill, fill);
    int cx = tr.left + D(27), cy = (tr.top + tr.bottom) / 2;
    COLORREF gc = LerpC(fill, t.ok, a);
    HBRUSH gb = CreateSolidBrush(gc);
    HPEN gp = (HPEN)GetStockObject(NULL_PEN);
    HGDIOBJ ob = SelectObject(dc, gb), op = SelectObject(dc, gp);
    Ellipse(dc, cx - D(9), cy - D(9), cx + D(9), cy + D(9));
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(gb);
    COLORREF tick = LerpC(gc, RGB(255, 255, 255), a);
    Line(dc, cx - D(4), cy, cx - D(1), cy + D(3), tick, D(2));
    Line(dc, cx - D(1), cy + D(3), cx + D(5), cy - D(4), tick, D(2));
    Txt(dc, g_ui.toastText,
        R(tr.left + D(46), tr.top, tr.right - tr.left - D(54), tr.bottom - tr.top),
        g_ui.fPill, text, DT_SINGLELINE | DT_LEFT | DT_VCENTER | DT_END_ELLIPSIS);
}
static void PaintToast(HDC dc) {
    if (!g_ui.toastOn) return;
    double a = ToastAlpha();
    if (a > 0) DrawToast(dc, a);
}

static void Paint(HDC dc) {
    const Theme& t = T();
    RECT all = R(0, 0, g_ui.cx, g_ui.cy);
    HBRUSH bg = CreateSolidBrush(t.bg);
    FillRect(dc, &all, bg); DeleteObject(bg);

    // thin brand gradient across the very top
    GradientH(dc, R(0, 0, g_ui.cx, D(5)), t.accent, t.accent2);

    // brand row: real app icon, title, version pill, one-line subtitle
    RECT bi = BrandIcon();
    if (g_ui.hAppIcon)
        DrawIconEx(dc, bi.left, bi.top, g_ui.hAppIcon,
                   bi.right - bi.left, bi.bottom - bi.top, 0, nullptr, DI_NORMAL);
    else
        RoundRect2(dc, bi, D(10), t.accent, t.accent);
    int tx = bi.right + D(12);
    Txt(dc, L"BatFix", R(tx, D(10), D(150), D(32)), g_ui.fTitle, t.text,
        DT_SINGLELINE | DT_LEFT | DT_VCENTER);
    RECT vp = R(tx + D(106), D(16), D(72), D(22));
    RoundRect2(dc, vp, D(11), t.accentSoft, t.accentSoft);
    Txt(dc, L"v" + W(BATFIX_VERSION_WTEXT), vp, g_ui.fSmall, t.accent,
        DT_SINGLELINE | DT_CENTER | DT_VCENTER);
    Txt(dc, L"拖入 bat / cmd，中文一次修好",
        R(tx, D(43), D(420), D(22)), g_ui.fSub, t.muted,
        DT_SINGLELINE | DT_LEFT | DT_VCENTER);

    // theme toggle
    RECT tb = ThemeRect();
    RoundRect2(dc, tb, D(15), t.card, t.border);
    int cxp = (tb.left + tb.right) / 2, cyp = (tb.top + tb.bottom) / 2;
    HBRUSH ib = CreateSolidBrush(g_ui.dark ? t.accent2 : t.warn);
    HGDIOBJ oi = SelectObject(dc, ib);
    HPEN np = (HPEN)GetStockObject(NULL_PEN); HGDIOBJ on = SelectObject(dc, np);
    Ellipse(dc, cxp - D(5), cyp - D(5), cxp + D(5), cyp + D(5));
    SelectObject(dc, oi); SelectObject(dc, on); DeleteObject(ib);
    if (g_ui.dark) {
        HBRUSH cb = CreateSolidBrush(t.card); HGDIOBJ oc = SelectObject(dc, cb);
        Ellipse(dc, cxp - D(1), cyp - D(7), cxp + D(9), cyp + D(3));
        SelectObject(dc, oc); DeleteObject(cb);
    }

    // update check: quiet by default; a red dot appears ONLY when a newer
    // release was actually found. Network failure looks exactly like idle.
    RECT ur = UpdateRect();
    int us = UpdateState();
    bool uHot = g_ui.hover == 41, uNew = us == UPD_AVAILABLE;
    RoundRect2(dc, ur, D(15), uNew ? t.accentSoft : (uHot ? t.hover : t.card),
               uNew ? t.accent : t.border);
    W uLab = us == UPD_CHECKING ? W(L"检查中…") :
             (us == UPD_LATEST ? W(L"已是最新") :
              (uNew ? W(L"发现 ") + DisplayVer(g_newVer) : W(L"检查更新")));
    Txt(dc, uLab,
        R(ur.left + D(8), ur.top, ur.right - ur.left - D(16), ur.bottom - ur.top),
        g_ui.fPill, uNew ? t.accent : (uHot ? t.text : t.muted),
        DT_SINGLELINE | DT_CENTER | DT_VCENTER | DT_END_ELLIPSIS);
    if (uNew) {
        int rr = D(10);
        RECT dot = R(ur.right - D(6), ur.top - D(4), rr, rr);
        HBRUSH rb = CreateSolidBrush(t.err);
        HPEN rp = CreatePen(PS_SOLID, D(2), t.card);
        HGDIOBJ ob = SelectObject(dc, rb), op = SelectObject(dc, rp);
        Ellipse(dc, dot.left, dot.top, dot.right, dot.bottom);
        SelectObject(dc, ob); SelectObject(dc, op);
        DeleteObject(rb); DeleteObject(rp);
    }

    // info bar: "completely free" + MIT note + clickable open-source address
    RECT ib2 = InfoBar();
    RoundRect2(dc, ib2, D(10), t.freeBg, LerpC(t.freeBg, t.ok, 0.32));
    RECT badge = R(ib2.left + D(12), ib2.top + D(7), D(88), D(24));
    RoundRect2(dc, badge, D(12), t.ok, t.ok);
    Txt(dc, L"完全免费", badge, g_ui.fPill, RGB(255, 255, 255),
        DT_SINGLELINE | DT_CENTER | DT_VCENTER);
    Txt(dc, L"MIT 协议 · 无广告 · 不上传文件",
        R(badge.right + D(12), ib2.top, D(250), ib2.bottom - ib2.top),
        g_ui.fSmall, t.freeFg, DT_SINGLELINE | DT_LEFT | DT_VCENTER);
    RECT gh = GithubRect();
    bool ghHot = g_ui.hover == 40;
    Txt(dc, L"github.com/yutils/BatFix  \u2197",
        R(gh.left, gh.top, gh.right - gh.left - D(6), gh.bottom - gh.top),
        g_ui.fSmall, ghHot ? t.accent2 : t.link,
        DT_SINGLELINE | DT_RIGHT | DT_VCENTER);
    if (ghHot)
        Line(dc, gh.right - D(190), gh.bottom - D(5), gh.right - D(6),
             gh.bottom - D(5), t.link, 1);

    // drop zone: soft vertical gradient + circular upload glyph
    RECT dr = DropRect();
    bool hot = g_ui.hover == 1;
    GradientRound(dc, dr, D(14),
                  hot ? t.accentSoft : t.card,
                  hot ? LerpC(t.accentSoft, t.card, .35) : LerpC(t.card, t.accentSoft, .55));
    RoundBorder(dc, dr, D(14), hot ? t.accent : t.border, hot ? 2 : 1);
    int icx = (dr.left + dr.right) / 2, icy = dr.top + D(35);
    HBRUSH db = CreateSolidBrush(hot ? t.accent : t.accentSoft);
    HGDIOBJ od = SelectObject(dc, db);
    HPEN dp = (HPEN)GetStockObject(NULL_PEN); HGDIOBJ odp = SelectObject(dc, dp);
    Ellipse(dc, icx - D(19), icy - D(19), icx + D(19), icy + D(19));
    SelectObject(dc, od); SelectObject(dc, odp); DeleteObject(db);
    COLORREF ic = hot ? RGB(255, 255, 255) : t.accent;
    Line(dc, icx, icy + D(9), icx, icy - D(8), ic, D(2));
    Line(dc, icx - D(6), icy - D(2), icx, icy - D(8), ic, D(2));
    Line(dc, icx + D(6), icy - D(2), icx, icy - D(8), ic, D(2));
    Txt(dc, L"拖入 .bat / .cmd 文件或文件夹",
        R(dr.left, dr.top + D(62), dr.right - dr.left, D(24)), g_ui.fBody, t.text,
        DT_SINGLELINE | DT_CENTER | DT_VCENTER);
    Txt(dc, L"或点击选择", R(dr.left, dr.top + D(88), dr.right - dr.left, D(20)),
        g_ui.fSmall, t.muted, DT_SINGLELINE | DT_CENTER | DT_VCENTER);

    // option checkboxes (2 x 2). Plain square + check mark: impossible to
    // mistake for a button, and the narrow hit box prevents accidental taps.
    static const wchar_t* labels[4] = {
        L"修复中文乱码", L"转换前自动备份", L"统一 CRLF 换行", L"修复已乱码文本"
    };
    for (int i = 0; i < 4; ++i) {
        RECT it = CheckItem(i);
        bool on = g_ui.check[i];
        bool hv = g_ui.hover == 10 + i;
        if (hv) RoundRect2(dc, it, D(6), t.hover, t.hover);
        int bs = D(16);
        RECT box = R(it.left + D(2), it.top + (D(28) - bs) / 2, bs, bs);
        RoundRect2(dc, box, D(4), on ? t.accent : t.card, on ? t.accent : t.border);
        if (on) {
            int x0 = box.left + D(4), y0 = box.top + D(8);
            Line(dc, x0, y0, x0 + D(3), y0 + D(3), RGB(255, 255, 255), D(2));
            Line(dc, x0 + D(3), y0 + D(3), x0 + D(9), y0 - D(4), RGB(255, 255, 255), D(2));
        }
        Txt(dc, labels[i], R(it.left + D(26), it.top, it.right - it.left - D(28), D(28)),
            g_ui.fPill, on ? t.text : t.muted,
            DT_SINGLELINE | DT_LEFT | DT_VCENTER | DT_END_ELLIPSIS);
    }

    // ANSI source encoding is not a boolean -> explicit dropdown
    RECT er = EncodingRect();
    RoundRect2(dc, er, D(6), g_ui.hover == 14 ? t.hover : t.card, t.border);
    Txt(dc, L"源编码  " + W(cpNames[g_ui.cpIdx]) + L"  \u25be",
        R(er.left + D(10), er.top, er.right - er.left - D(20), er.bottom - er.top),
        g_ui.fPill, t.text, DT_SINGLELINE | DT_LEFT | DT_VCENTER);

    Line(dc, D(28), D(346), g_ui.cx - D(28), D(346), t.border);

    // four compact stat cards instead of one long line of text
    static const wchar_t* statLabels[4] = { L"已处理", L"已修改", L"已备份", L"失败" };
    int vals[4] = { g_ui.done, g_ui.changed, g_ui.backed, g_ui.errors };
    COLORREF statCols[4] = { t.accent, t.warn, t.ok, t.err };
    for (int i = 0; i < 4; ++i) {
        RECT sr = StatRect(i);
        RoundRect2(dc, sr, D(9), t.card, t.border);
        RoundRect2(dc, R(sr.left + D(8), sr.top + D(10), D(3), D(22)), D(2),
                   statCols[i], statCols[i]);
        Txt(dc, Itow(vals[i]),
            R(sr.left + D(17), sr.top + D(4), D(38), D(32)), g_ui.fNum, t.text,
            DT_SINGLELINE | DT_LEFT | DT_VCENTER);
        Txt(dc, statLabels[i],
            R(sr.left + D(58), sr.top, sr.right - sr.left - D(60), sr.bottom - sr.top),
            g_ui.fSmall, t.muted, DT_SINGLELINE | DT_LEFT | DT_VCENTER);
    }
    Txt(dc, L"清空", ClearRect(), g_ui.fSmall,
        g_ui.hover == 20 ? t.accent : t.muted, DT_SINGLELINE | DT_CENTER | DT_VCENTER);

    // result list
    RECT lr = ListRect();
    int vr = VisibleRows();
    if (g_ui.rows.empty()) {
        RoundBorder(dc, lr, D(10), t.border);
        Txt(dc, L"转换结果显示在这里 · 点击任意一行看详情", lr, g_ui.fSmall, t.muted,
            DT_SINGLELINE | DT_CENTER | DT_VCENTER);
        PaintToast(dc);
        return;
    }
    int maxScroll = (int)g_ui.rows.size() > vr ? (int)g_ui.rows.size() - vr : 0;
    if (g_ui.scroll > maxScroll) g_ui.scroll = maxScroll;
    if (g_ui.scroll < 0) g_ui.scroll = 0;
    for (int i = 0; i < vr && (size_t)(i + g_ui.scroll) < g_ui.rows.size(); ++i) {
        const Row& row = g_ui.rows[(size_t)(i + g_ui.scroll)];
        int y = lr.top + i * D(28);
        if (i % 2 == 1)
            RoundRect2(dc, R(lr.left, y, lr.right - lr.left, D(28)), D(6),
                       t.hover, t.hover);
        Line(dc, lr.left, y + D(27), lr.right, y + D(27), t.border);
        COLORREF k = row.kind == 2 ? t.err : (row.kind == 1 ? t.warn : t.ok);
        HBRUSH kb = CreateSolidBrush(k); HGDIOBJ ok = SelectObject(dc, kb);
        HPEN kp = (HPEN)GetStockObject(NULL_PEN); HGDIOBJ op = SelectObject(dc, kp);
        Ellipse(dc, lr.left + D(4), y + D(11), lr.left + D(10), y + D(17));
        SelectObject(dc, ok); SelectObject(dc, op); DeleteObject(kb);
        Txt(dc, row.file, R(lr.left + D(18), y, D(310), D(28)), g_ui.fSmall, t.text,
            DT_SINGLELINE | DT_LEFT | DT_VCENTER | DT_END_ELLIPSIS);
        Txt(dc, row.brief, R(lr.right - D(300), y, D(296), D(28)), g_ui.fSmall, t.muted,
            DT_SINGLELINE | DT_RIGHT | DT_VCENTER | DT_END_ELLIPSIS);
    }
    if (maxScroll > 0) {
        int track = lr.bottom - lr.top;
        int thumb = (int)((double)vr / g_ui.rows.size() * track);
        if (thumb < D(20)) thumb = D(20);
        int pos = (int)((double)g_ui.scroll / maxScroll * (track - thumb));
        RoundRect2(dc, R(lr.right + D(6), lr.top + pos, D(3), thumb), D(2), t.border, t.border);
    }
    PaintToast(dc);
}

static W ShortEnc(const W& e) {
    if (e.find(L"ANSI") != W::npos) return L"GBK";
    if (e.find(L"BOM") != W::npos && e.find(L"UTF-8") != W::npos) return L"UTF-8 BOM";
    if (e.find(L"UTF-16") != W::npos) return L"UTF-16";
    if (e.find(L"UTF-32") != W::npos) return L"UTF-32";
    if (e.find(L"ASCII") != W::npos) return L"ASCII";
    if (e.find(L"二进制") != W::npos) return L"跳过";
    if (e.find(L"空文件") != W::npos) return L"空文件";
    return L"UTF-8";
}
static Options UiOptions() {
    Options o;
    o.manageChcp = g_ui.check[0];
    o.fixLineTail = g_ui.check[0];
    o.backup = g_ui.check[1];
    o.normalizeNewline = g_ui.check[2];
    o.ansiCp = cps[g_ui.cpIdx];
    o.repairMojibake = g_ui.check[3];
    return o;
}
static void ConvertPaths(const std::vector<W>& paths) {
    std::vector<W> files;
    for (const W& p : paths) CollectPath(p, files);
    if (files.empty()) {
        g_ui.rows.push_back({ L"没有找到 .bat / .cmd 文件", L"拖入文件或文件夹", L"", 1 });
        InvalidateRect(g_ui.hwnd, nullptr, FALSE); return;
    }
    Options o = UiOptions();
    for (const W& f : files) {
        Report r;
        bool ok = ConvertOne(f, f, o, r);
        ++g_ui.done;
        if (r.changed) ++g_ui.changed;
        if (r.backedUp) ++g_ui.backed;
        if (!ok) ++g_ui.errors;
        W brief = ShortEnc(r.enc) + L" · ";
        if (r.padded) brief += L"补 " + Itow(r.padded) + L" 处";
        else if (r.rewritten) brief += L"改写 " + Itow(r.rewritten) + L" 处";
        else if (!r.changed) brief += L"无需修改";
        else brief += L"换行/编码";
        if (!r.warns.empty()) brief += L" · " + Itow((long long)r.warns.size()) + L" 提示";
        Row row;
        row.file = Basename(f);
        row.brief = brief;
        row.kind = !ok ? 2 : (r.warns.empty() ? 0 : 1);
        row.detail = ReportLine(r);
        g_ui.rows.push_back(row);
    }
    g_ui.scroll = 1000000;
    InvalidateRect(g_ui.hwnd, nullptr, FALSE);
}
static void OpenFileDialog() {
    wchar_t buf[32768] = { 0 };
    OPENFILENAMEW of = {};
    of.lStructSize = sizeof(of);
    of.hwndOwner = g_ui.hwnd;
    of.lpstrFilter = L"批处理 (*.bat;*.cmd)\0*.bat;*.cmd\0所有文件\0*.*\0\0";
    of.lpstrFile = buf; of.nMaxFile = 32768;
    of.Flags = OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_FILEMUSTEXIST | OFN_HIDEREADONLY;
    if (!GetOpenFileNameW(&of)) return;
    std::vector<W> paths;
    if (of.nFileOffset > 0 && buf[of.nFileOffset - 1] == L'\0') {
        W dir(buf, of.nFileOffset - 1);
        wchar_t* p = buf + of.nFileOffset;
        while (*p) { paths.push_back(dir + L"\\" + p); p += wcslen(p) + 1; }
    } else paths.push_back(buf);
    ConvertPaths(paths);
}

// Hidden self-test: render the exact same Paint() into an offscreen DIB and
// save a 24-bit BMP. Used to produce a real (not mocked) UI preview.
static bool SavePreviewBmp(const W& path, int w, int h) {
    HDC sdc = GetDC(nullptr);
    HDC mem = CreateCompatibleDC(sdc);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w;
    bi.bmiHeader.biHeight = -h;                 // top-down rows
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 24;
    bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bm = CreateDIBSection(sdc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (!bm || !bits) { DeleteDC(mem); ReleaseDC(nullptr, sdc); return false; }
    HGDIOBJ old = SelectObject(mem, bm);
    int ocx = g_ui.cx, ocy = g_ui.cy;
    g_ui.cx = w; g_ui.cy = h;
    Paint(mem);
    g_ui.cx = ocx; g_ui.cy = ocy;

    int row = ((w * 3 + 3) / 4) * 4;
    BITMAPFILEHEADER fh = {};
    fh.bfType = 0x4D42;
    fh.bfSize = sizeof(fh) + sizeof(BITMAPINFOHEADER) + (DWORD)row * h;
    fh.bfOffBits = sizeof(fh) + sizeof(BITMAPINFOHEADER);
    HANDLE hf = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    bool ok = hf != INVALID_HANDLE_VALUE;
    if (ok) {
        DWORD wr = 0;
        WriteFile(hf, &fh, sizeof(fh), &wr, nullptr);
        WriteFile(hf, &bi.bmiHeader, sizeof(BITMAPINFOHEADER), &wr, nullptr);
        for (int y = 0; y < h; ++y)
            WriteFile(hf, (BYTE*)bits + (size_t)y * row, (DWORD)row, &wr, nullptr);
        CloseHandle(hf);
    }
    SelectObject(mem, old);
    DeleteObject(bm); DeleteDC(mem); ReleaseDC(nullptr, sdc);
    return ok;
}

static void OnUpdateClick(HWND hwnd) {
    int st = UpdateState();
    if (st == UPD_AVAILABLE) {
        // The red dot is already the notification; clicking gives the
        // version comparison plus a one-click download link.
        W msg = L"当前版本：v" + W(BATFIX_VERSION_WTEXT) + L"\r\n" +
                L"最新版本：" + DisplayVer(g_newVer) + L"\r\n\r\n" +
                L"是否前往 GitHub Releases 下载新版本？";
        if (MessageBoxW(hwnd, msg.c_str(), L"发现新版本",
                        MB_YESNO | MB_ICONINFORMATION | MB_DEFBUTTON1) == IDYES) {
            const wchar_t* page = g_newUrl[0] ? g_newUrl : kUpdatePage;
            ShellExecuteW(hwnd, L"open", page, nullptr, nullptr, SW_SHOWNORMAL);
        }
        InterlockedExchange(&g_toastOnLatest, 0);
        return;
    }
    // Every explicit click performs a real re-check. Only when that check
    // actually reaches GitHub and confirms "up to date" do we toast; the
    // automatic startup check never toasts, and any failure stays silent.
    InterlockedExchange(&g_toastOnLatest, 1);
    if (st == UPD_CHECKING) return;   // result will arrive via WM_APP_UPDATE_RESULT
    StartUpdateCheck(hwnd);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g_ui.hwnd = hwnd;
        HDC dc = GetDC(hwnd);
        g_ui.S = GetDeviceCaps(dc, LOGPIXELSX) / 96.0;
        ReleaseDC(hwnd, dc);
        if (g_ui.S < 1.0) g_ui.S = 1.0;
        RebuildFonts();
        g_ui.hAppIcon = (HICON)LoadImageW(GetModuleHandleW(nullptr),
            MAKEINTRESOURCEW(BATFIX_ICON_ID), IMAGE_ICON, D(40), D(40), LR_DEFAULTCOLOR);
        RECT rc; GetClientRect(hwnd, &rc);
        g_ui.cx = rc.right; g_ui.cy = rc.bottom;
        DragAcceptFiles(hwnd, TRUE);
        return 0;
    }
    case WM_SIZE:
        g_ui.cx = LOWORD(lp); g_ui.cy = HIWORD(lp);
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC hdc = BeginPaint(hwnd, &ps);
        HDC mem = CreateCompatibleDC(hdc);
        HBITMAP bm = CreateCompatibleBitmap(hdc, g_ui.cx, g_ui.cy);
        HGDIOBJ old = SelectObject(mem, bm);
        Paint(mem);
        BitBlt(hdc, 0, 0, g_ui.cx, g_ui.cy, mem, 0, 0, SRCCOPY);
        SelectObject(mem, old); DeleteObject(bm); DeleteDC(mem);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_DROPFILES: {
        HDROP h = (HDROP)wp;
        UINT n = DragQueryFileW(h, 0xFFFFFFFF, nullptr, 0);
        std::vector<W> paths;
        for (UINT i = 0; i < n; ++i) {
            UINT len = DragQueryFileW(h, i, nullptr, 0);
            W s((size_t)len + 1, L'\0');           // +1 for the NUL terminator
            DragQueryFileW(h, i, &s[0], len + 1);
            s.resize(len);
            paths.push_back(s);
        }
        DragFinish(h);
        ConvertPaths(paths);
        return 0;
    }
    case WM_COPYDATA: {
        COPYDATASTRUCT* c = (COPYDATASTRUCT*)lp;
        if (c && c->dwData == 0x42415446 && c->cbData > 1) {
            W s((const wchar_t*)c->lpData, c->cbData / sizeof(wchar_t));
            std::vector<W> paths;
            size_t st = 0;
            while (st < s.size()) {
                size_t e = s.find(L'\n', st); if (e == W::npos) e = s.size();
                W part = s.substr(st, e - st);
                if (!part.empty() && part.back() == L'\0') part.pop_back();
                if (!part.empty()) paths.push_back(part);
                st = e + 1;
            }
            if (!paths.empty()) ConvertPaths(paths);
        }
        return TRUE;
    }
    case WM_MOUSEMOVE: {
        int h = HitTest((short)LOWORD(lp), (short)HIWORD(lp));
        if (h != g_ui.hover) { g_ui.hover = h; InvalidateRect(hwnd, nullptr, FALSE); }
        TRACKMOUSEEVENT tm = {}; tm.cbSize = sizeof(tm);
        tm.dwFlags = TME_LEAVE; tm.hwndTrack = hwnd;
        TrackMouseEvent(&tm);
        return 0;
    }
    case WM_MOUSELEAVE:
        g_ui.hover = 0; InvalidateRect(hwnd, nullptr, FALSE); return 0;
    case WM_MOUSEWHEEL: {
        int delta = GET_WHEEL_DELTA_WPARAM(wp);
        g_ui.scroll -= delta / WHEEL_DELTA * 2;
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    }
    case WM_LBUTTONDOWN:
        g_ui.pressHit = HitTest((short)LOWORD(lp), (short)HIWORD(lp));
        return 0;
    case WM_LBUTTONUP: {
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        int h = HitTest(x, y);
        // Only act when press and release land on the SAME control. This
        // stops a click-drag that starts elsewhere from flipping an option.
        if (h != g_ui.pressHit) { g_ui.pressHit = 0; return 0; }
        g_ui.pressHit = 0;
        if (h == 40) {
            ShellExecuteW(hwnd, L"open", L"https://github.com/yutils/BatFix",
                          nullptr, nullptr, SW_SHOWNORMAL);
        } else if (h == 41) OnUpdateClick(hwnd);
        else if (h == 1) OpenFileDialog();
        else if (h == 2) { g_ui.dark = !g_ui.dark; InvalidateRect(hwnd, nullptr, FALSE); }
        else if (h == 20) {
            g_ui.rows.clear();
            g_ui.done = g_ui.changed = g_ui.errors = g_ui.backed = 0;
            g_ui.scroll = 0;
            InvalidateRect(hwnd, nullptr, FALSE);
        } else if (h >= 10 && h <= 13) {
            g_ui.check[h - 10] = !g_ui.check[h - 10];
            InvalidateRect(hwnd, nullptr, FALSE);
        } else if (h == 14) {
            ShowEncodingMenu(hwnd);
        } else if (h == 30) {
            RECT lr = ListRect();
            int idx = (y - lr.top) / D(28) + g_ui.scroll;
            if (idx >= 0 && (size_t)idx < g_ui.rows.size() && !g_ui.rows[idx].detail.empty())
                MessageBoxW(hwnd, g_ui.rows[idx].detail.c_str(), L"转换详情", MB_OK | MB_ICONINFORMATION);
        }
        return 0;
    }
    case WM_APP_UPDATE_RESULT: {
        // Background thread finished (state already published with a barrier).
        if (InterlockedCompareExchange(&g_toastOnLatest, 0, 0) == 1) {
            InterlockedExchange(&g_toastOnLatest, 0);
            if ((int)wp == UPD_LATEST)
                ShowToast(hwnd, LatestToastText());
            // AVAILABLE -> red dot is the notification; FAILED -> silent.
        }
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    }
    case WM_TIMER:
        if ((UINT)wp == IDT_TOAST) {
            if (GetTickCount() - g_ui.toastStart >= kToastLife) {
                KillTimer(hwnd, IDT_TOAST);
                g_ui.toastOn = false;
                g_ui.toastPinned = false;
                g_ui.toastText.clear();
                TraceToast(L"TOAST_END");
            }
            InvalidateRect(hwnd, nullptr, FALSE);   // fade in / fade out
            return 0;
        }
        break;
    case WM_DESTROY:
        KillTimer(hwnd, IDT_TOAST);
        for (HFONT f : { g_ui.fTitle, g_ui.fSub, g_ui.fBody, g_ui.fSmall,
                         g_ui.fPill, g_ui.fStat, g_ui.fNum })
            if (f) DeleteObject(f);
        if (g_ui.hAppIcon) DestroyIcon(g_ui.hAppIcon);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    SetProcessDPIAware();
    HDC sdc = GetDC(nullptr);
    g_ui.S = GetDeviceCaps(sdc, LOGPIXELSX) / 96.0;
    ReleaseDC(nullptr, sdc);
    if (g_ui.S < 1.0) g_ui.S = 1.0;
    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    bool cli = false, smoke = false, darkShot = false;
    bool selftestUpdate = false, updateSync = false, updateDemo = false;
    bool noUpdateCheck = false, toastDemo = false;
    W shotPath, updateFile;
    std::vector<W> startup;
    for (int i = 1; i < argc; ++i) {
        if (lstrcmpiW(argv[i], L"--cli") == 0) cli = true;
        else if (lstrcmpiW(argv[i], L"--smoke") == 0) smoke = true;
        else if (lstrcmpiW(argv[i], L"--dark") == 0) darkShot = true;
        else if (lstrcmpiW(argv[i], L"--selftest-update") == 0) selftestUpdate = true;
        else if (lstrcmpiW(argv[i], L"--update-sync") == 0) updateSync = true;
        else if (lstrcmpiW(argv[i], L"--update-demo") == 0) updateDemo = true;
        else if (lstrcmpiW(argv[i], L"--toast-demo") == 0) toastDemo = true;
        else if (lstrcmpiW(argv[i], L"--no-update-check") == 0) noUpdateCheck = true;
        else if (lstrcmpiW(argv[i], L"--shot") == 0 && i + 1 < argc) shotPath = argv[++i];
        else if (lstrcmpiW(argv[i], L"--update-file") == 0 && i + 1 < argc) updateFile = argv[++i];
        else if (lstrcmpiW(argv[i], L"--out") == 0 || lstrcmpiW(argv[i], L"--report") == 0 ||
                 lstrcmpiW(argv[i], L"--cp") == 0) { ++i; }
        else if (argv[i][0] == L'-' && argv[i][1] == L'-') { }
        else startup.push_back(argv[i]);
    }

    g_updateFile = updateFile;      // own a copy before CommandLineToArgvW is freed
    // Developer diagnostics run before the singleton check so they also work
    // while a GUI instance is open. Neither one creates a window.
    if (selftestUpdate || updateSync) {
        LocalFree(argv);
        AttachConsole(ATTACH_PARENT_PROCESS);
        return selftestUpdate ? RunUpdateSelfTest() : RunUpdateSyncProbe();
    }

    HANDLE mutex = CreateMutexW(nullptr, TRUE, kMutex);
    bool first = mutex && GetLastError() != ERROR_ALREADY_EXISTS;
    if (!first) {
        HWND other = FindWindowW(kClass, nullptr);
        if (other) {
            if (!startup.empty() && !cli) {
                W payload;
                for (const W& p : startup) { payload += p; payload += L'\n'; }
                COPYDATASTRUCT c = {}; c.dwData = 0x42415446;
                c.cbData = (DWORD)(payload.size() * sizeof(wchar_t));
                c.lpData = (PVOID)payload.c_str();
                SendMessageTimeoutW(other, WM_COPYDATA, 0, (LPARAM)&c, SMTO_ABORTIFHUNG, 3000, nullptr);
            }
            ShowWindow(other, SW_RESTORE);
            SetForegroundWindow(other);
        }
        if (cli) { LocalFree(argv); return 2; }
        LocalFree(argv);
        return 0;
    }
    if (cli) { Options def; int rc = RunCli(argc, argv, def); LocalFree(argv); return rc; }
    LocalFree(argv);

    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    HINSTANCE inst = wc.hInstance;
    wc.hIcon = (HICON)LoadImageW(inst, MAKEINTRESOURCEW(BATFIX_ICON_ID), IMAGE_ICON,
                                 GetSystemMetrics(SM_CXICON), GetSystemMetrics(SM_CYICON),
                                 LR_DEFAULTCOLOR);
    wc.hIconSm = (HICON)LoadImageW(inst, MAKEINTRESOURCEW(BATFIX_ICON_ID), IMAGE_ICON,
                                   GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON),
                                   LR_DEFAULTCOLOR);
    if (!wc.hIcon) wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    if (!wc.hIconSm) wc.hIconSm = wc.hIcon;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = kClass;
    RegisterClassExW(&wc);

    W title = L"BatFix v" + W(BATFIX_VERSION_WTEXT);
    HWND hwnd = CreateWindowExW(0, kClass, title.c_str(), WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, D(838), D(602), nullptr, nullptr, wc.hInstance, nullptr);
    if (!hwnd) return 1;
    ShowWindow(hwnd, SW_SHOW);
    UpdateWindow(hwnd);
    if (!shotPath.empty()) {
        // Sample rows so the preview shows the populated state of the UI.
        g_ui.dark = darkShot;
        g_ui.S = 1.0;              // fixed-size preview, independent of monitor DPI
        RebuildFonts();
        g_ui.done = 4; g_ui.changed = 3; g_ui.errors = 0; g_ui.backed = 4;
        g_ui.rows.push_back({ L"测试01.bat", L"UTF-8 · 换行 CRLF · 1 提示", L"", 1 });
        g_ui.rows.push_back({ L"测试02.bat", L"UTF-8 · 补 5 处", L"", 0 });
        g_ui.rows.push_back({ L"测试03.bat", L"GBK · 补 5 处 · 1 提示", L"", 1 });
        g_ui.rows.push_back({ L"测试04.bat", L"UTF-8 BOM · 1 提示", L"", 1 });
        if (updateDemo) {       // hardcoded preview state for doc screenshots
            InterlockedExchange(&g_updState, UPD_AVAILABLE);
            CopyPod(g_newVer, 64, L"0.0.2");
            CopyPod(g_newUrl, 512, kUpdatePage);
        } else if (!g_updateFile.empty()) {
            // Real pipeline: local JSON -> parse -> compare -> publish state.
            W v, u;
            int st = FetchLatest(v, u)
                   ? ClassifyVersion(W(BATFIX_VERSION_WTEXT), v) : UPD_FAILED;
            InterlockedExchange(&g_updState, st);
            if (st == UPD_AVAILABLE) {
                CopyPod(g_newVer, 64, v);
                CopyPod(g_newUrl, 512, u);
            } else { g_newVer[0] = 0; g_newUrl[0] = 0; }
        }
        if (toastDemo) {
            g_ui.toastText = LatestToastText();
            g_ui.toastOn = true;
            g_ui.toastPinned = true;   // fully visible, no timer, for screenshots
        }
        SavePreviewBmp(shotPath, 820, 560);
        PostMessageW(hwnd, WM_CLOSE, 0, 0);
    } else if (smoke) PostMessageW(hwnd, WM_CLOSE, 0, 0);
    else {
        if (!startup.empty()) ConvertPaths(startup);
        if (!noUpdateCheck) StartUpdateCheck(hwnd);   // async; never blocks the window
    }

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    if (mutex) { ReleaseMutex(mutex); CloseHandle(mutex); }
    return 0;
}

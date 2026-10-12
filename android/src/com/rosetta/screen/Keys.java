package com.rosetta.screen;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;

import java.util.HashMap;

/**
 * The tablet's own keyboard for the PC, drawn along the bottom of the screen. It types into whatever has the focus on
 * the PC: characters go as "u:<hex code point>", the rest as named keys ("backspace", "ctrl+c", "shift+left" ...).
 * Shift and Ctrl count for the next key (Shift twice = caps lock), #+= switches to symbols, backspace and the arrows
 * repeat while held. Several fingers can type at once.
 */
class Keys extends View {
    interface Out { void key(String action); void hide(); }

    static final String[][] ABC = {
        {"esc", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "bksp"},
        {"tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "å"},
        {"a", "s", "d", "f", "g", "h", "j", "k", "l", "ø", "æ", "enter"},
        {"shift", "z", "x", "c", "v", "b", "n", "m", ",", ".", "-", "up"},
        {"ctrl", "sym", "space", "left", "down", "right", "hide"}};
    static final String[][] SYM = {
        ABC[0],
        {"tab", "!", "@", "#", "$", "%", "&", "*", "(", ")", "=", "?"},
        {"\"", "'", ":", ";", "/", "\\", "|", "<", ">", "+", "_", "enter"},
        {"shift", "~", "`", "[", "]", "{", "}", "€", "£", "§", "^", "up"},
        ABC[4]};
    static final int AMBER = Color.rgb(240, 177, 42);

    final Out out;
    boolean sym, shift, caps, ctrl;
    long lastShift;
    final HashMap<Integer, String> held = new HashMap<Integer, String>();     // pointer id -> key under it
    final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG), text = new Paint(Paint.ANTI_ALIAS_FLAG);
    final RectF rect = new RectF();
    String repAction;

    Keys(Context c, Out out) {
        super(c);
        this.out = out;
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
    }

    static float width(String k) {
        if (k.equals("space")) return 5f;
        if (k.equals("bksp") || k.equals("tab") || k.equals("enter") || k.equals("shift") || k.equals("ctrl")
                || k.equals("sym") || k.equals("hide")) return 1.5f;
        return 1f;                                                             // every row is 12.5 units wide
    }

    static String named(String k) {                                            // keys that are not characters
        if (k.equals("bksp")) return "backspace";
        if (k.equals("esc") || k.equals("tab") || k.equals("enter") || k.equals("left") || k.equals("right")
                || k.equals("up") || k.equals("down")) return k;
        return null;
    }

    String label(String k) {
        if (k.length() == 1) return (shift || caps) && !sym ? k.toUpperCase() : k;
        if (k.equals("shift")) return caps ? "CAPS" : "shift";
        if (k.equals("sym")) return sym ? "abc" : "#+=";
        if (k.equals("left")) return "←";
        if (k.equals("right")) return "→";
        if (k.equals("up")) return "↑";
        if (k.equals("down")) return "↓";
        if (k.equals("space")) return "";
        return k;
    }

    String at(float x, float y) {
        String[][] rows = sym ? SYM : ABC;
        int r = Math.max(0, Math.min(4, (int) (y / (getHeight() / 5f))));
        float unit = getWidth() / 12.5f, left = 0;
        for (String k : rows[r]) {
            left += width(k) * unit;
            if (x < left) return k;
        }
        return null;
    }

    /** A touch (finger or pen) inside the keyboard; top = where the keyboard starts in the event's coordinates. */
    void touch(MotionEvent e, float top) {
        int act = e.getActionMasked(), i = e.getActionIndex();
        if (act == MotionEvent.ACTION_DOWN || act == MotionEvent.ACTION_POINTER_DOWN) {
            String k = at(e.getX(i), e.getY(i) - top);
            if (k != null) { held.put(e.getPointerId(i), k); press(k); }
        } else if (act == MotionEvent.ACTION_POINTER_UP) {
            held.remove(e.getPointerId(i));
            stopRepeat();
        } else if (act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_CANCEL) {
            held.clear();
            stopRepeat();
        }
        invalidate();
    }

    void press(String k) {
        long now = SystemClock.uptimeMillis();
        if (k.equals("shift")) {
            if (caps) { caps = false; shift = false; }
            else if (shift && now - lastShift < 400) { caps = true; shift = false; }
            else shift = !shift;
            lastShift = now;
            return;
        }
        if (k.equals("ctrl")) { ctrl = !ctrl; return; }
        if (k.equals("sym")) { sym = !sym; return; }
        if (k.equals("hide")) { out.hide(); return; }
        String n = named(k), a;
        if (n != null) {
            a = (ctrl ? "ctrl+" : "") + (shift ? "shift+" : "") + n;            // shift+arrows select, ctrl+arrows jump words
        } else {
            String c = k.equals("space") ? " " : k;
            if (ctrl) a = c.charAt(0) < 128 && Character.isLetterOrDigit(c.charAt(0))
                    ? "ctrl+" + (shift ? "shift+" : "") + c.toLowerCase() : null;          // ctrl+c, ctrl+shift+z ...
            else a = "u:" + Integer.toHexString((shift || caps) && !sym ? c.toUpperCase().codePointAt(0) : c.codePointAt(0));
        }
        if (a != null) out.key(a);
        shift = false;
        ctrl = false;
        if (n != null && !n.equals("esc") && !n.equals("tab") && !n.equals("enter")) startRepeat(a);
    }

    final Runnable rep = new Runnable() {
        public void run() {
            if (repAction == null) return;
            out.key(repAction);
            postDelayed(this, 50);
        }
    };

    void startRepeat(String a) { repAction = a; removeCallbacks(rep); postDelayed(rep, 400); }

    void stopRepeat() { repAction = null; removeCallbacks(rep); }

    @Override
    protected void onDraw(Canvas c) {
        String[][] rows = sym ? SYM : ABC;
        float rowH = getHeight() / 5f, unit = getWidth() / 12.5f, gap = 5f;
        c.drawColor(0xFF141418);
        for (int r = 0; r < 5; r++) {
            float x = 0;
            for (String k : rows[r]) {
                float w = width(k) * unit;
                boolean special = k.length() > 1;
                boolean on = held.containsValue(k) || (k.equals("shift") && (shift || caps)) || (k.equals("ctrl") && ctrl);
                fill.setColor(on ? AMBER : special ? 0xFF24242A : 0xFF34343C);
                rect.set(x + gap, r * rowH + gap, x + w - gap, (r + 1) * rowH - gap);
                c.drawRoundRect(rect, 10, 10, fill);
                String l = label(k);
                text.setColor(on ? Color.BLACK : special ? AMBER : 0xFFEDEDED);
                text.setTextSize(l.length() > 1 ? rowH * 0.28f : rowH * 0.42f);
                c.drawText(l, rect.centerX(), rect.centerY() - (text.descent() + text.ascent()) / 2, text);
                x += w;
            }
        }
    }
}

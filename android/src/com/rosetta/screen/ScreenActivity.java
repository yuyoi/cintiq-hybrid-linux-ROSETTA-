package com.rosetta.screen;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Point;
import android.view.Gravity;
import android.media.MediaCodec;
import android.media.MediaFormat;
import android.os.Bundle;
import android.os.Environment;
import android.os.StrictMode;
import android.os.SystemClock;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

import java.security.MessageDigest;

import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Rosetta Screen: the tablet as a wireless pen display for the PC.
 *
 * Video: the PC sends whole H.264 frames as numbered UDP fragments ("V" packets). Complete frames go straight into the
 * Tegra's hardware decoder (MediaCodec) and onto the screen; a frame that is late or incomplete is dropped, never queued.
 * Input: pen (hover, pressure, eraser, barrel button), finger and hardware keys go back to the PC as the same
 * HMAC-signed packets the Linux side uses ("P", "T", "K"), plus a "H" hello so the PC knows where to send video.
 * Config: /sdcard/rosetta/pc.conf (host=, port=, secret=<hex>, video_port=), written by the PC side.
 */
public class ScreenActivity extends Activity implements SurfaceHolder.Callback {
    String host = "255.255.255.255";                 // until pc.conf or the PC's answer says otherwise
    int port = 5600, videoPort = 5700;
    byte[] secret;
    Mac mac, verify;
    InetAddress pc;
    DatagramSocket out;
    volatile DatagramSocket vsock;                 // video socket: also sends the hellos (keeps the path open)
    String remote;                                 // home address for use away from home (pc.conf: remote=)
    volatile InetAddress remoteAddr;
    long remoteResolved;
    Cipher aes;
    SecretKeySpec vkey;
    long seq;

    SurfaceView view;
    TextView status;
    volatile boolean running;
    Thread videoThread, helloThread;
    volatile String info = "starting";
    volatile int fps, dropped, frameCount;

    long lastPen;
    volatile String hint;                          // a short note in the status line ("hold Back to leave")
    volatile long hintUntil;

    Keys keys;                                     // the tablet's own keyboard for the PC
    boolean kbTouch;                               // the current touch started on the keyboard
    int pan;                                       // picture slid up by this much so the text box stays above the keyboard
    long ctlSeq;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        StrictMode.setThreadPolicy(new StrictMode.ThreadPolicy.Builder().permitAll().build());   // tiny UDP sends from the UI thread
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        root = new Overlay(this);
        root.setBackgroundColor(Color.BLACK);
        view = new SurfaceView(this);
        root.addView(view, new FrameLayout.LayoutParams(-1, -1));
        status = new TextView(this);
        status.setTextColor(Color.rgb(240, 177, 42));
        status.setTextSize(16);
        status.setBackgroundColor(0xAA000000);
        status.setPadding(16, 8, 16, 8);
        root.addView(status, new FrameLayout.LayoutParams(-2, -2));
        keys = new Keys(this, new Keys.Out() {
            public void key(String a) { sendKey(a); }
            public void hide() { hideKeys(); }
        });
        keys.setVisibility(View.GONE);
        root.addView(keys, new FrameLayout.LayoutParams(-1, 0, Gravity.BOTTOM));
        View black = new View(this);
        black.setBackgroundColor(Color.BLACK);
        setContentView(black);                                       // the activity itself stays an empty black page
        view.getHolder().addCallback(this);
        loadConfig();
    }

    // ------------------------------------------------------------------ full screen above the Android system bar
    // Android 4.2 tablets cannot hide their system bar, so the video lives in a system overlay window, which Android
    // draws above the bar. Nothing is switched off: when we leave, the overlay is simply removed.
    Overlay root;
    boolean shown;

    class Overlay extends FrameLayout {
        Overlay(Context c) { super(c); setFocusableInTouchMode(true); }
        @Override public boolean dispatchTouchEvent(MotionEvent e) { handle(e, true); return true; }
        @Override public boolean dispatchGenericMotionEvent(MotionEvent e) { handle(e, false); return true; }
        @Override public boolean dispatchKeyEvent(KeyEvent e) {             // the activity's handlers, not View's own
            return e.getAction() == KeyEvent.ACTION_DOWN ? ScreenActivity.this.onKeyDown(e.getKeyCode(), e)
                                                         : ScreenActivity.this.onKeyUp(e.getKeyCode(), e);
        }
    }

    void showOverlay() {
        if (shown) return;
        Point size = new Point();
        getWindowManager().getDefaultDisplay().getRealSize(size);
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(size.x, size.y,
                WindowManager.LayoutParams.TYPE_SYSTEM_ERROR,
                WindowManager.LayoutParams.FLAG_FULLSCREEN | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                PixelFormat.OPAQUE);
        lp.gravity = Gravity.TOP | Gravity.LEFT;
        lp.x = 0; lp.y = 0;
        // Added through the application's window manager, not the activity's: the activity's would tie the overlay to
        // the activity, and Android hides it the moment anything (a Home press from its bar) sends the activity back.
        try { appWm().addView(root, lp); shown = true; root.requestFocus(); }
        catch (Exception e) { info = "overlay refused (" + e + ")"; setContentView(root); shown = false; }
    }

    void hideOverlay() {
        if (!shown) return;
        try { appWm().removeView(root); } catch (Exception ignored) { }
        shown = false;
    }

    WindowManager appWm() { return (WindowManager) getApplicationContext().getSystemService(Context.WINDOW_SERVICE); }

    // ------------------------------------------------------------------ keyboard
    // Shown by the Menu key, or by the PC when a tap from here puts its focus in a text box. bottom = that box's lower
    // edge (0..65535 down the picture, 0 = unknown): if the keyboard would cover it, the picture slides up.
    void showKeys(int bottom) {
        int h = root.getHeight();
        if (h < 2) return;
        int kh = h * 2 / 5;
        FrameLayout.LayoutParams kl = (FrameLayout.LayoutParams) keys.getLayoutParams();
        if (kl.height != kh) { kl.height = kh; keys.setLayoutParams(kl); }
        keys.setVisibility(View.VISIBLE);
        int fb = (int) ((long) bottom * h / 65535), room = h - kh - 16;
        setPan(bottom > 0 && fb > room ? Math.min(kh, fb - room) : 0);
    }

    void hideKeys() {
        keys.setVisibility(View.GONE);
        setPan(0);
    }

    void setPan(int p) {
        if (p == pan) return;
        pan = p;
        FrameLayout.LayoutParams vl = (FrameLayout.LayoutParams) view.getLayoutParams();
        vl.height = root.getHeight();
        vl.topMargin = -p;
        view.setLayoutParams(vl);
    }

    void loadConfig() {
        File f = new File(Environment.getExternalStorageDirectory(), "rosetta/pc.conf");
        try {
            BufferedReader r = new BufferedReader(new FileReader(f));
            String ln;
            while ((ln = r.readLine()) != null) {
                int h = ln.indexOf('#');
                if (h >= 0) ln = ln.substring(0, h);
                int eq = ln.indexOf('=');
                if (eq < 0) continue;
                String k = ln.substring(0, eq).trim(), v = ln.substring(eq + 1).trim();
                if (k.equals("host")) host = v;
                else if (k.equals("remote")) remote = v.length() > 0 ? v : null;
                else if (k.equals("port")) port = Integer.parseInt(v);
                else if (k.equals("video_port")) videoPort = Integer.parseInt(v);
                else if (k.equals("secret")) secret = v.getBytes("US-ASCII");   // the key is the hex text itself, like the PC and Linux sides
            }
            r.close();
            mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            sha.update(secret);
            sha.update("|video".getBytes("US-ASCII"));
            vkey = new SecretKeySpec(sha.digest(), "AES");          // the video is AES-256-CTR encrypted
            aes = Cipher.getInstance("AES/CTR/NoPadding");
            pc = InetAddress.getByName(host);
            out = new DatagramSocket();
            out.setBroadcast(true);
            verify = Mac.getInstance("HmacSHA256");
            verify.init(new SecretKeySpec(secret, "HmacSHA256"));
            info = "waiting for the PC (" + host + ")";
        } catch (Exception e) {
            info = "no config: " + f + " (" + e + ")";
        }
    }

    static byte[] hex(String s) {
        byte[] b = new byte[s.length() / 2];
        for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    // root commands (the boot menu's "reboot into Linux"), one at a time
    static final java.util.concurrent.ExecutorService SU = java.util.concurrent.Executors.newSingleThreadExecutor();

    static void su(final String cmd) {
        SU.execute(new Runnable() { public void run() {
            try { Runtime.getRuntime().exec(new String[] {"su", "-c", cmd}).waitFor(); } catch (Exception ignored) { }
        } });
    }

    @Override
    protected void onResume() {
        super.onResume();
        showOverlay();
    }

    // The overlay stays up while Android does anything underneath (a tap that lands on its hidden Back / Recents
    // buttons, a notification): only holding Back closes the screen.
    @Override
    protected void onDestroy() {
        hideOverlay();
        super.onDestroy();
    }

    void hint(String s) {
        hint = s;
        hintUntil = SystemClock.uptimeMillis() + 2000;
        status.setText(s);
        status.setVisibility(View.VISIBLE);
    }

    // ------------------------------------------------------------------ packets to the PC
    void send(ByteBuffer bb, int toPort) { sendFrom(out, bb, pc, toPort); }

    synchronized void sendFrom(DatagramSocket sock, ByteBuffer bb, InetAddress to, int toPort) {
        if (mac == null || sock == null || to == null) return;
        byte[] p = Arrays.copyOf(bb.array(), bb.position());
        byte[] tag = mac.doFinal(p);
        byte[] pkt = Arrays.copyOf(p, p.length + 8);
        System.arraycopy(tag, 0, pkt, p.length, 8);
        try { sock.send(new DatagramPacket(pkt, pkt.length, to, toPort)); } catch (Exception ignored) { }
    }

    synchronized int nextSeq() {
        seq = Math.max(seq + 1, System.currentTimeMillis() & 0xFFFFFFFFL);
        return (int) seq;
    }

    ByteBuffer pkt(char kind, int size) {
        ByteBuffer bb = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN);
        bb.put((byte) kind).putInt(nextSeq());
        return bb;
    }

    static int norm(float v, int size) {
        return Math.max(0, Math.min(65535, (int) (v * 65535f / Math.max(1, size - 1))));
    }

    void sendPen(boolean inRange, boolean contact, boolean barrel, boolean eraser, float x, float y, float pressure) {
        int flags = (inRange ? 1 : 0) | (contact ? 2 : 0) | (barrel ? 4 : 0) | (eraser ? 8 : 0);
        int press = contact ? Math.max(1, Math.min(1023, (int) (pressure * 1023))) : 0;
        ByteBuffer bb = pkt('P', 16);
        bb.put((byte) flags).putShort((short) norm(x, view.getWidth())).putShort((short) norm(y + pan, view.getHeight()))
          .putShort((short) press).put((byte) 0).put((byte) 0);
        send(bb, port);
    }

    void sendFingers() {                                            // every finger that is down ('M'), none = all lifted
        int n = 0;
        for (boolean d : fdown) if (d) n++;
        ByteBuffer bb = pkt('M', 6 + 5 * n);
        bb.put((byte) n);
        for (int id = 0; id < 10; id++)
            if (fdown[id]) bb.put((byte) id).putShort((short) norm(fx[id], view.getWidth())).putShort((short) norm(fy[id] + pan, view.getHeight()));
        send(bb, port);
    }

    void sendKey(String action) {
        ByteBuffer bb = pkt('K', 32);
        byte[] a = action.getBytes();
        bb.put(Arrays.copyOf(a, 24));
        send(bb, port);
    }

    // ------------------------------------------------------------------ input

    void handle(MotionEvent e, boolean touchStream) {
        if (view.getWidth() < 2) return;
        int tool = e.getToolType(0), act = e.getActionMasked();
        boolean kbOn = keys.getVisibility() == View.VISIBLE;
        float kbTop = root.getHeight() - keys.getHeight();
        if (touchStream && act == MotionEvent.ACTION_DOWN) kbTouch = kbOn && e.getY(0) >= kbTop;
        if (kbTouch) {                                                // the whole touch belongs to the keyboard
            if (touchStream) {
                keys.touch(e, kbTop);
                if (act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_CANCEL) kbTouch = false;
            }
            return;
        }
        if (!touchStream && kbOn && e.getY(0) >= kbTop) return;       // pen hovering over the keyboard (a stroke that
                                                                      // started on the picture still ends on the PC)
        if (tool == MotionEvent.TOOL_TYPE_STYLUS || tool == MotionEvent.TOOL_TYPE_ERASER) {
            lastPen = SystemClock.uptimeMillis();
            if (tState == LIVE) { Arrays.fill(fdown, false); sendFingers(); }       // the pen takes over from the hand
            if (tState != IDLE) { root.removeCallbacks(goLive); tState = IGNORE; }
            boolean eraser = tool == MotionEvent.TOOL_TYPE_ERASER;
            boolean barrel = (e.getButtonState() & (MotionEvent.BUTTON_SECONDARY | MotionEvent.BUTTON_TERTIARY)) != 0;
            boolean contact = touchStream && (act == MotionEvent.ACTION_DOWN || act == MotionEvent.ACTION_MOVE
                    || act == MotionEvent.ACTION_POINTER_DOWN);
            boolean inRange = act != MotionEvent.ACTION_HOVER_EXIT && act != MotionEvent.ACTION_CANCEL;
            for (int i = 0; i < e.getHistorySize(); i++)            // all the in-between points: smooth strokes
                sendPen(inRange, contact, barrel, eraser, e.getHistoricalX(0, i), e.getHistoricalY(0, i), e.getHistoricalPressure(0, i));
            sendPen(inRange, contact, barrel, eraser, e.getX(0), e.getY(0), e.getPressure(0));
        } else if (touchStream && tool == MotionEvent.TOOL_TYPE_FINGER) {
            fingers(e);
        }
    }

    // ------------------------------------------------------------------ fingers
    // Every finger goes to Windows as a real touch contact (pinch zoom, two-finger pan). A quick two-finger tap is undo
    // instead, so that it can't click too, a new touch waits ~0.1 s (0.26 s once a second finger lands) before it goes
    // out; a touch that moves goes out at once.
    static final int IDLE = 0, WAIT = 1, LIVE = 2, IGNORE = 3;
    int tState = IDLE;
    long tDown;
    int most;                                                        // most fingers down at once in this touch
    final float[] fx = new float[10], fy = new float[10], sx = new float[10], sy = new float[10];
    final boolean[] fdown = new boolean[10];
    final Runnable goLive = new Runnable() { public void run() {
        if (tState != WAIT) return;
        long age = SystemClock.uptimeMillis() - tDown;
        if (most >= 2 && age < 260) { root.postDelayed(this, 260 - age); return; }
        tState = LIVE;                                               // held still: it's a press / pinch, send it
        sendFingers();
    } };

    void fingers(MotionEvent e) {
        int act = e.getActionMasked();
        long now = SystemClock.uptimeMillis();
        if (act == MotionEvent.ACTION_DOWN) {
            Arrays.fill(fdown, false);
            most = 0;
            tDown = now;
            tState = now - lastPen < 400 ? IGNORE : WAIT;            // palm rejection: the pen was just here
            if (tState == WAIT) root.postDelayed(goLive, 110);
        }
        if (tState == IGNORE || tState == IDLE) return;
        for (int i = 0; i < e.getPointerCount(); i++) {
            int id = e.getPointerId(i);
            if (id >= 10) continue;
            fx[id] = e.getX(i);
            fy[id] = e.getY(i);
            if (!fdown[id]) { fdown[id] = true; sx[id] = fx[id]; sy[id] = fy[id]; }
        }
        boolean end = act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_CANCEL;
        if (act == MotionEvent.ACTION_POINTER_UP) {
            int id = e.getPointerId(e.getActionIndex());
            if (id < 10) fdown[id] = false;
        }
        int n = 0;
        for (boolean d : fdown) if (d) n++;
        most = Math.max(most, n);
        if (tState == WAIT) {
            if (end) {                                               // lifted before anything went out: a tap
                root.removeCallbacks(goLive);
                tState = IDLE;
                if (most == 2 && now - tDown < 300) { sendKey("ctrl+z"); return; }   // two-finger tap = undo
                if (most == 1) { sendFingers(); Arrays.fill(fdown, false); sendFingers(); }   // one finger = a click
                Arrays.fill(fdown, false);
                return;
            }
            boolean moved = false;
            for (int id = 0; id < 10; id++)
                if (fdown[id] && Math.hypot(fx[id] - sx[id], fy[id] - sy[id]) > 24) moved = true;
            if (!moved) return;
            root.removeCallbacks(goLive);
            tState = LIVE;
        }
        if (end) Arrays.fill(fdown, false);
        sendFingers();
        if (end) tState = IDLE;
    }

    @Override
    public boolean onKeyDown(int code, KeyEvent e) {
        String a = null;
        switch (code) {
            case KeyEvent.KEYCODE_BACK:                                        // held = leave; a tap can't close it
                if (e.getRepeatCount() == 0) hint("hold Back to leave the wireless screen");
                else if (e.getEventTime() - e.getDownTime() > 800) finish();
                return true;
            case KeyEvent.KEYCODE_VOLUME_UP: a = "ctrl+z"; break;
            case KeyEvent.KEYCODE_VOLUME_DOWN: a = "ctrl+shift+z"; break;
            case KeyEvent.KEYCODE_MENU:                                        // the tablet keyboard on / off
                if (e.getRepeatCount() == 0) { if (keys.getVisibility() == View.VISIBLE) hideKeys(); else showKeys(0); }
                return true;
            case KeyEvent.KEYCODE_SEARCH: a = "screen"; break;                // PC flips mirror <-> extended screen
        }
        if (a == null) return super.onKeyDown(code, e);
        if (e.getRepeatCount() == 0) sendKey(a);
        return true;
    }

    @Override
    public boolean onKeyUp(int code, KeyEvent e) {
        if (code == KeyEvent.KEYCODE_VOLUME_UP || code == KeyEvent.KEYCODE_VOLUME_DOWN || code == KeyEvent.KEYCODE_MENU
                || code == KeyEvent.KEYCODE_SEARCH || code == KeyEvent.KEYCODE_BACK) return true;
        return super.onKeyUp(code, e);
    }

    // ------------------------------------------------------------------ video
    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        running = true;
        videoThread = new Thread(new Runnable() { public void run() { videoLoop(); } }, "video");
        helloThread = new Thread(new Runnable() { public void run() { helloLoop(); } }, "hello");
        videoThread.start();
        helloThread.start();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) { }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        running = false;
        try { videoThread.join(1500); } catch (InterruptedException ignored) { }
    }

    void helloLoop() {
        InetAddress bcast = null;
        try { bcast = InetAddress.getByName("255.255.255.255"); } catch (Exception ignored) { }
        while (running) {
            // Hellos leave from the video socket: at home the broadcast finds the PC on any Wi-Fi, away from home the
            // hello to the home address opens the way back through this network's router for the video.
            if (remote != null && SystemClock.uptimeMillis() - remoteResolved > 30000) {
                try { remoteAddr = InetAddress.getByName(remote); } catch (Exception ignored) { }
                remoteResolved = SystemClock.uptimeMillis();
            }
            DatagramSocket v = vsock;
            if (v != null) {
                sendFrom(v, pkt('H', 8), pc, port + 1);
                sendFrom(v, pkt('H', 8), bcast, port + 1);
                if (remoteAddr != null) sendFrom(v, pkt('H', 8), remoteAddr, port + 1);
            }
            boolean hinting = SystemClock.uptimeMillis() < hintUntil;
            final String s = hinting ? hint : info + (fps > 0 ? "   " + fps + " fps" + (dropped > 0 ? "  dropped " + dropped : "") : "");
            final boolean hide = fps > 0 && dropped == 0 && !hinting;
            runOnUiThread(new Runnable() { public void run() {
                status.setText(s);
                status.setVisibility(hide ? View.GONE : View.VISIBLE);
            } });
            fps = frameCount; frameCount = 0; dropped = 0;
            SystemClock.sleep(1000);
        }
    }

    boolean signed(byte[] b, int n) {                              // the PC's HMAC tag (last 8 bytes) is right
        byte[] tag;
        synchronized (this) { verify.update(b, 0, n - 8); tag = verify.doFinal(); }
        for (int k = 0; k < 8; k++) if (tag[k] != b[n - 8 + k]) return false;
        return true;
    }

    static int nal(byte[] f, int from) {                          // index of the next 00 00 01 start code, or -1
        for (int i = from; i + 2 < f.length; i++)
            if (f[i] == 0 && f[i + 1] == 0 && f[i + 2] == 1) return i;
        return -1;
    }

    static byte[] findNal(byte[] f, int type) {                    // a NAL unit (with a 4-byte start code) of this type
        int i = nal(f, 0);
        while (i >= 0) {
            int s = i + 3, next = nal(f, s);
            int end = next < 0 ? f.length : (next > 0 && f[next - 1] == 0 ? next - 1 : next);
            if ((f[s] & 0x1f) == type) {
                byte[] n = new byte[4 + end - s];
                n[3] = 1;
                System.arraycopy(f, s, n, 4, end - s);
                return n;
            }
            i = next;
        }
        return null;
    }

    void videoLoop() {
        DatagramSocket in = null;
        MediaCodec dec = null;
        ByteBuffer[] inputs = null;
        MediaCodec.BufferInfo bi = new MediaCodec.BufferInfo();
        byte[] buf = new byte[2048];
        int cur = -1, need = 0, got = 0;
        byte[][] frags = null;
        boolean done = true;
        // Latency probe (only if /sdcard/rosetta/probe exists): a second hardware decoder outputs into memory, and the
        // moment the PC's flip square (top-left) changes brightness we tell the PC (UDP 5610), which times the trip.
        boolean probe = new File(Environment.getExternalStorageDirectory(), "rosetta/probe").exists();
        MediaCodec pdec = null;
        ByteBuffer[] pin = null, pout = null;
        MediaCodec.BufferInfo pbi = new MediaCodec.BufferInfo();
        int stride = 1920, cfmt = 0, lastBright = -1;
        DatagramSocket psock = null;
        try {
            if (probe) psock = new DatagramSocket();
            in = new DatagramSocket(null);
            in.setReuseAddress(true);
            in.bind(new InetSocketAddress(videoPort));
            in.setReceiveBufferSize(4 << 20);
            in.setSoTimeout(5);
            in.setBroadcast(true);
            vsock = in;
            byte[] session = new byte[6], iv = new byte[16];
            DatagramPacket dp = new DatagramPacket(buf, buf.length);
            while (running) {
                boolean have = false;
                try { in.receive(dp); have = true; } catch (SocketTimeoutException t) { }
                if (have && dp.getLength() >= 13 && buf[0] == 'A') {               // the PC answering our hello
                    if (signed(buf, dp.getLength()) && !dp.getAddress().equals(pc)) { pc = dp.getAddress(); host = pc.getHostAddress(); info = "PC " + host + "  hardware decoder"; }
                    continue;
                }
                if (have && dp.getLength() == 17 && buf[0] == 'C' && signed(buf, 17)) {   // the PC: keyboard up / down
                    ByteBuffer c = ByteBuffer.wrap(buf, 1, 8).order(ByteOrder.LITTLE_ENDIAN);
                    long s = c.getInt() & 0xffffffffL;
                    byte cmd = c.get();
                    final boolean show = c.get() != 0;
                    final int bottom = c.getShort() & 0xffff;
                    if (cmd == 'k' && (s > ctlSeq || ctlSeq - s > 1000000)) {     // newer than the last one (no replays)
                        ctlSeq = s;
                        runOnUiThread(new Runnable() { public void run() { if (show) showKeys(bottom); else hideKeys(); } });
                    }
                    continue;
                }
                if (have && dp.getLength() > 15 && buf[0] == 'W') {
                    boolean same = true;                                           // a new PC session restarts the frame count
                    for (int k = 0; k < 6; k++) if (buf[1 + k] != session[k]) same = false;
                    if (!same) { System.arraycopy(buf, 1, session, 0, 6); cur = -1; done = true; }
                    ByteBuffer h = ByteBuffer.wrap(buf, 7, 8).order(ByteOrder.LITTLE_ENDIAN);
                    int id = h.getInt(), idx = h.getShort() & 0xffff, cnt = h.getShort() & 0xffff;
                    if (id != cur) {
                        if (cur != -1 && id - cur < 0) continue;               // a straggler from an older frame
                        if (!done) dropped++;                                  // the previous frame never completed
                        cur = id; need = cnt; got = 0; frags = new byte[cnt][]; done = false;
                    }
                    if (!done && idx < need && frags[idx] == null) {
                        System.arraycopy(buf, 1, iv, 0, 12);                    // session + frame + fragment, counter 0
                        aes.init(Cipher.DECRYPT_MODE, vkey, new IvParameterSpec(iv));
                        frags[idx] = aes.doFinal(buf, 15, dp.getLength() - 15);
                        if (++got == need) {
                            done = true;
                            int len = 0;
                            for (byte[] fr : frags) len += fr.length;
                            byte[] frame = new byte[len];
                            int o = 0;
                            for (byte[] fr : frags) { System.arraycopy(fr, 0, frame, o, fr.length); o += fr.length; }
                            if (dec == null) {
                                byte[] sps = findNal(frame, 7), pps = findNal(frame, 8);
                                if (sps != null && pps != null) {
                                    MediaFormat fmt = MediaFormat.createVideoFormat("video/avc", 1920, 1080);
                                    fmt.setByteBuffer("csd-0", ByteBuffer.wrap(sps));
                                    fmt.setByteBuffer("csd-1", ByteBuffer.wrap(pps));
                                    fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 2 << 20);
                                    dec = MediaCodec.createDecoderByType("video/avc");
                                    dec.configure(fmt, view.getHolder().getSurface(), null, 0);
                                    dec.start();
                                    inputs = dec.getInputBuffers();
                                    info = "PC " + host + "  hardware decoder";
                                    if (probe) {
                                        pdec = MediaCodec.createDecoderByType("video/avc");
                                        pdec.configure(fmt, null, null, 0);
                                        pdec.start();
                                        pin = pdec.getInputBuffers();
                                        pout = pdec.getOutputBuffers();
                                        info = "PC " + host + "  LATENCY PROBE";
                                    }
                                }
                            }
                            if (dec != null) {
                                int ix = dec.dequeueInputBuffer(2000);
                                if (ix >= 0) {
                                    ByteBuffer ib = inputs[ix];
                                    ib.clear();
                                    ib.put(frame);
                                    dec.queueInputBuffer(ix, 0, frame.length, SystemClock.uptimeMillis() * 1000, 0);
                                } else {
                                    dropped++;                                         // decoder busy: drop, never queue
                                }
                                if (pdec != null) {
                                    int px = pdec.dequeueInputBuffer(2000);
                                    if (px >= 0) {
                                        ByteBuffer pb = pin[px];
                                        pb.clear();
                                        pb.put(frame);
                                        pdec.queueInputBuffer(px, 0, frame.length, SystemClock.uptimeMillis() * 1000, 0);
                                    }
                                }
                            }
                        }
                    }
                }
                if (pdec != null) {
                    while (true) {
                        int ox = pdec.dequeueOutputBuffer(pbi, 0);
                        if (ox == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                            MediaFormat of = pdec.getOutputFormat();
                            if (of.containsKey("stride")) stride = of.getInteger("stride");
                            if (of.containsKey("color-format")) cfmt = of.getInteger("color-format");
                            info = "PC " + host + "  LATENCY PROBE  stride " + stride + " fmt 0x" + Integer.toHexString(cfmt);
                            continue;
                        }
                        if (ox == MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED) { pout = pdec.getOutputBuffers(); continue; }
                        if (ox < 0) break;
                        int off = pbi.offset + 60 * stride + 60;                       // luma at (60, 60)
                        if (off < pbi.offset + pbi.size) {
                            int bright = (pout[ox].get(off) & 0xff) > 128 ? 1 : 0;
                            if (lastBright >= 0 && bright != lastBright && pc != null) {
                                byte[] note = "flip".getBytes();
                                try { psock.send(new DatagramPacket(note, note.length, pc, 5610)); } catch (Exception ignored) { }
                            }
                            lastBright = bright;
                        }
                        pdec.releaseOutputBuffer(ox, false);
                    }
                }
                if (dec != null) {                                                     // show every decoded frame at once
                    while (true) {
                        int ox = dec.dequeueOutputBuffer(bi, 0);
                        if (ox >= 0) { dec.releaseOutputBuffer(ox, true); frameCount++; }
                        else if (ox == MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED || ox == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) continue;
                        else break;
                    }
                }
            }
        } catch (Exception e) {
            info = "video error: " + e;
        } finally {
            if (dec != null) { try { dec.stop(); } catch (Exception ignored) { } dec.release(); }
            if (pdec != null) { try { pdec.stop(); } catch (Exception ignored) { } pdec.release(); }
            if (psock != null) psock.close();
            if (in != null) in.close();
        }
    }
}

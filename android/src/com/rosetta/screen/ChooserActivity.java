package com.rosetta.screen;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Rosetta boot menu: shown at every power-on (and from its own icon), above the lock screen.
 * WIRELESS SCREEN opens Rosetta Screen, LINUX DESKTOP reboots into the native Linux on the recovery slot,
 * ANDROID just closes the menu.
 */
public class ChooserActivity extends Activity {
    static final int ORANGE = Color.rgb(240, 177, 42), BG = Color.rgb(10, 12, 14), PANEL = Color.rgb(28, 30, 34);
    TextView note;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(BG);

        TextView title = new TextView(this);
        title.setText("ROSETTA");
        title.setTextColor(ORANGE);
        title.setTextSize(64);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);
        TextView sub = new TextView(this);
        sub.setText("CINTIQ // TEGRA4 // pick a mode");
        sub.setTextColor(Color.rgb(127, 208, 255));
        sub.setTextSize(20);
        sub.setGravity(Gravity.CENTER);
        sub.setPadding(0, 0, 0, 48);
        root.addView(sub);

        root.addView(button("WIRELESS SCREEN", "the PC's second screen, with the pen", new View.OnClickListener() {
            public void onClick(View v) {
                startActivity(new Intent(ChooserActivity.this, ScreenActivity.class));
                finish();
            }
        }));
        root.addView(button("LINUX DESKTOP", "reboot into native Linux (Krita, games, PC mode)", new View.OnClickListener() {
            public void onClick(View v) {
                note.setText("rebooting into Linux...");
                ScreenActivity.su("pm enable com.android.systemui; reboot recovery");
            }
        }));
        root.addView(button("ANDROID", "just use Android", new View.OnClickListener() {
            public void onClick(View v) { finish(); }
        }));

        note = new TextView(this);
        note.setTextColor(Color.rgb(200, 200, 200));
        note.setTextSize(18);
        note.setGravity(Gravity.CENTER);
        note.setPadding(0, 32, 0, 0);
        root.addView(note);
        setContentView(root);
    }

    View button(String label, String hint, View.OnClickListener click) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        Button bt = new Button(this);
        bt.setText(label);
        bt.setTextColor(ORANGE);
        bt.setTextSize(30);
        bt.setTypeface(Typeface.DEFAULT_BOLD);
        GradientDrawable d = new GradientDrawable();
        d.setColor(PANEL);
        d.setStroke(4, ORANGE);
        d.setCornerRadius(18);
        bt.setBackgroundDrawable(d);
        bt.setPadding(48, 28, 48, 28);
        bt.setOnClickListener(click);
        box.addView(bt, new LinearLayout.LayoutParams(760, LinearLayout.LayoutParams.WRAP_CONTENT));
        TextView h = new TextView(this);
        h.setText(hint);
        h.setTextColor(Color.rgb(150, 150, 160));
        h.setTextSize(16);
        h.setGravity(Gravity.CENTER);
        h.setPadding(0, 6, 0, 28);
        box.addView(h, new LinearLayout.LayoutParams(760, LinearLayout.LayoutParams.WRAP_CONTENT));
        return box;
    }
}

package com.rosetta.screen;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Opens the Rosetta boot menu once Android has finished starting. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())) {
            c.startActivity(new Intent(c, ChooserActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
    }
}

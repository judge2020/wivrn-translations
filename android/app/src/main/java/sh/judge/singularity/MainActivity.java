package sh.judge.singularity;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int AUDIO = 1;
    private static final int PROJECTION = 2;
    private static final int NOTIFICATIONS = 3;
    private static final int INK = Color.rgb(237, 244, 239);
    private static final int MINT = Color.rgb(189, 243, 215);
    private static final int MUTED = Color.rgb(190, 205, 195);
    private static final int CARD = Color.rgb(27, 38, 32);
    private static final int[] SPEAKERS = {
            MINT, 0xffb8d9ff, 0xffffe0a2, 0xfffbcaf1, 0xffdcd1ff, 0xffffc4ab
    };

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private EditText address;
    private EditText token;
    private EditText language;
    private CheckBox translate;
    private TextView status;
    private LinearLayout rows;
    private LinearLayout settings;
    private Button settingsButton;
    private SharedPreferences preferences;
    private boolean watching;
    private boolean captureRequested;
    private boolean visible;
    private int generation;
    private String currentRows = "";

    @Override
    public void onCreate(Bundle saved) {
        super.onCreate(saved);
        preferences = getSharedPreferences("settings", MODE_PRIVATE);
        watching = preferences.getBoolean("watching", false) || CaptureService.running;
        captureRequested = CaptureService.running || preferences.getBoolean("capture_requested", false);
        ScrollView scroll = new ScrollView(this);
        scroll.setClipToPadding(false);
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setPadding(dp(24), dp(22), dp(24), dp(24));
        scroll.addView(screen);
        setContentView(scroll);

        TextView title = text("Singularity", 34, INK);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        screen.addView(title);
        status = text("Configure your companion to begin.", 15, MINT);
        screen.addView(status);
        rows = new LinearLayout(this);
        rows.setOrientation(LinearLayout.VERTICAL);
        screen.addView(rows);

        settingsButton = button("Hide setup", () -> showSettings(settings.getVisibility() != View.VISIBLE));
        screen.addView(settingsButton);
        settings = new LinearLayout(this);
        settings.setOrientation(LinearLayout.VERTICAL);
        screen.addView(settings);
        address = field("Companion URL", preferences.getString("address", ""), "http://192.168.1.10:8765",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        token = field("Companion token", preferences.getString("token", ""), "Hex token from your Linux host",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        language = field("Source language", preferences.getString("language", "auto"), "auto or a code such as ja",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        translate = new CheckBox(this);
        translate.setText("Translate capture to English");
        translate.setChecked(preferences.getBoolean("translate", false));
        settings.addView(translate);
        settings.addView(button("Monitor companion", () -> {
            if (saveSettings()) {
                stopService(new Intent(this, CaptureService.class));
                startMonitoring(false);
            }
        }));
        settings.addView(button("Capture VRChat playback", this::requestAudio));
        screen.addView(button("Stop", this::stopMonitoring));
        showSettings(!watching);
        showRows(new JSONArray());
    }

    @Override
    protected void onStart() {
        super.onStart();
        visible = true;
        poll();
    }

    @Override
    protected void onStop() {
        visible = false;
        generation++;
        main.removeCallbacksAndMessages(null);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }

    private void showSettings(boolean show) {
        settings.setVisibility(show ? View.VISIBLE : View.GONE);
        settingsButton.setText(show ? "Hide setup" : "Show setup");
    }

    private boolean saveSettings() {
        try {
            String endpoint = Companion.address(address.getText().toString());
            String secret = token.getText().toString().trim();
            String source = language.getText().toString().trim();
            if (!secret.matches("[a-fA-F0-9]{32,128}")) {
                throw new IllegalArgumentException("Enter the hexadecimal companion token.");
            }
            if (!source.matches("auto|[a-z]{2,3}")) {
                throw new IllegalArgumentException("Use auto or a source language code such as ja.");
            }
            preferences.edit().putString("address", endpoint).putString("token", secret)
                    .putString("language", source).putBoolean("translate", translate.isChecked()).apply();
            return true;
        } catch (IllegalArgumentException error) {
            status.setText(error.getMessage());
            return false;
        }
    }

    private void startMonitoring(boolean capture) {
        watching = true;
        captureRequested = capture;
        preferences.edit().putBoolean("watching", true).putBoolean("capture_requested", capture).apply();
        showSettings(false);
        status.setText("Connecting to companion…");
        generation++;
        main.removeCallbacksAndMessages(null);
        poll();
    }

    private void stopMonitoring() {
        watching = false;
        generation++;
        preferences.edit().putBoolean("watching", false).putBoolean("capture_requested", false).apply();
        main.removeCallbacksAndMessages(null);
        stopService(new Intent(this, CaptureService.class));
        status.setText("Stopped");
        showRows(new JSONArray());
        showSettings(true);
    }

    private void poll() {
        if (!visible || !watching) return;
        int attempt = generation;
        String endpoint = preferences.getString("address", "");
        String secret = preferences.getString("token", "");
        boolean capture = captureRequested;
        network.execute(() -> {
            JSONArray captions;
            String message;
            try {
                captions = Companion.latest(endpoint, secret);
                String captureStatus = CaptureService.status;
                message = capture ? (captureStatus.isEmpty() ? "Playback capture is idle." : captureStatus)
                        : "Monitoring companion";
            } catch (Exception error) {
                captions = new JSONArray();
                message = "Companion unavailable. Check the address, token and Wi-Fi.";
            }
            JSONArray result = captions;
            String state = message;
            main.post(() -> {
                if (!visible || !watching || generation != attempt) return;
                status.setText(state);
                showRows(result);
                main.postDelayed(this::poll, 600);
            });
        });
    }

    private void requestAudio() {
        if (!saveSettings()) return;
        if (CaptureService.running) {
            startMonitoring(true);
            return;
        }
        try {
            getPackageManager().getApplicationInfo(CaptureService.VRCHAT, 0);
        } catch (PackageManager.NameNotFoundException error) {
            status.setText("VRChat is not installed on this device. Use Monitor companion to view Linux captions.");
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO);
        } else {
            requestProjection();
        }
    }

    private void requestProjection() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED && !preferences.getBoolean("asked_notifications", false)) {
            preferences.edit().putBoolean("asked_notifications", true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATIONS);
            return;
        }
        MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
        try {
            startActivityForResult(manager.createScreenCaptureIntent(), PROJECTION);
        } catch (RuntimeException error) {
            status.setText("Playback sharing is unavailable. Use the Linux companion to capture audio.");
        }
    }

    @Override
    public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == NOTIFICATIONS || (request == AUDIO && results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED)) {
            requestProjection();
        } else if (request == AUDIO) {
            status.setText("Playback capture needs Android’s audio permission.");
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PROJECTION) return;
        if (result != RESULT_OK || data == null) {
            status.setText("Playback sharing was cancelled.");
            return;
        }
        Intent capture = new Intent(this, CaptureService.class)
                .putExtra("projection", data).putExtra("result", result)
                .putExtra("address", preferences.getString("address", ""))
                .putExtra("token", preferences.getString("token", ""))
                .putExtra("language", preferences.getString("language", "auto"))
                .putExtra("mode", preferences.getBoolean("translate", false) ? "translate" : "transcribe");
        try {
            startForegroundService(capture);
            startMonitoring(true);
        } catch (RuntimeException error) {
            status.setText("Android could not start playback capture.");
        }
    }

    private void showRows(JSONArray captions) {
        String signature = captions.toString();
        if (currentRows.equals(signature)) return;
        currentRows = signature;
        rows.removeAllViews();
        LinkedHashMap<String, List<JSONObject>> groups = new LinkedHashMap<>();
        for (int i = 0; i < captions.length(); i++) {
            JSONObject caption = captions.optJSONObject(i);
            if (caption == null) continue;
            int speaker = caption.optInt("speaker", 0);
            String key = speaker > 0 ? "Speaker " + speaker
                    : caption.optString("kind").equals("overlap") ? "Overlapping speech" : "Speech";
            groups.computeIfAbsent(key, unused -> new ArrayList<>()).add(caption);
        }
        if (groups.isEmpty()) {
            rows.addView(text("Waiting for speech", 22, MUTED));
            return;
        }
        groups.forEach((label, turns) -> {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            row.setPadding(dp(16), dp(12), dp(16), dp(14));
            GradientDrawable background = new GradientDrawable();
            background.setCornerRadius(dp(10));
            background.setColor(CARD);
            row.setBackground(background);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
            params.topMargin = dp(12);
            rows.addView(row, params);
            int speaker = turns.get(0).optInt("speaker", 0);
            TextView heading = text(label, 14, speaker > 0 ? SPEAKERS[(speaker - 1) % SPEAKERS.length] : MUTED);
            heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            row.addView(heading);
            for (JSONObject turn : turns) {
                TextView line = text(turn.optString("text"), 24, INK);
                line.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
                row.addView(line);
            }
        });
    }

    private EditText field(String label, String value, String hint, int inputType) {
        TextView name = text(label, 15, MUTED);
        settings.addView(name);
        EditText input = new EditText(this);
        input.setSingleLine();
        input.setInputType(inputType);
        input.setText(value);
        input.setHint(hint);
        input.setTextColor(INK);
        input.setHintTextColor(MUTED);
        input.setContentDescription(label);
        settings.addView(input);
        return input;
    }

    private Button button(String label, Runnable action) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextColor(INK);
        button.setBackgroundTintList(ColorStateList.valueOf(CARD));
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}

package sh.judge.singularity;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioPlaybackCaptureConfiguration;
import android.media.AudioRecord;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import java.util.concurrent.ArrayBlockingQueue;

public final class CaptureService extends Service {
    static final String VRCHAT = "com.vrchat.oculus.quest";
    static final String STOP = "sh.judge.singularity.STOP";
    private static final int SAMPLE_RATE = 16000;
    private static final int CHUNK_BYTES = SAMPLE_RATE * 2 * 6;
    static volatile boolean running;
    static volatile String status = "";

    private final Handler main = new Handler(Looper.getMainLooper());
    private MediaProjection projection;
    private Session session;
    private final MediaProjection.Callback projectionCallback = new MediaProjection.Callback() {
        @Override
        public void onStop() {
            status = "Playback sharing ended.";
            stopSelf();
        }
    };

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || STOP.equals(intent.getAction())) {
            status = "Playback capture stopped.";
            stopSelf();
            return START_NOT_STICKY;
        }
        if (session != null) return START_NOT_STICKY;
        try {
            startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
            Intent permission = Build.VERSION.SDK_INT >= 33
                    ? intent.getParcelableExtra("projection", Intent.class)
                    : intent.getParcelableExtra("projection");
            projection = getSystemService(MediaProjectionManager.class)
                    .getMediaProjection(intent.getIntExtra("result", 0), permission);
            if (projection == null) throw new IllegalStateException("Playback capture permission ended.");
            projection.registerCallback(projectionCallback, main);
            int uid = getPackageManager().getApplicationInfo(VRCHAT, 0).uid;
            AudioPlaybackCaptureConfiguration source = new AudioPlaybackCaptureConfiguration.Builder(projection)
                    .addMatchingUid(uid)
                    .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                    .addMatchingUsage(AudioAttributes.USAGE_GAME)
                    .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
                    .build();
            session = new Session(intent, source);
            running = true;
            status = "Listening for VRChat playback…";
            session.start();
        } catch (Exception error) {
            status = "Could not start playback capture. Check sharing permission and the VRChat install.";
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    private Notification notification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
                "capture", "Playback capture", NotificationManager.IMPORTANCE_LOW));
        int flags = PendingIntent.FLAG_IMMUTABLE;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), flags);
        PendingIntent stop = PendingIntent.getService(this, 0, new Intent(this, CaptureService.class).setAction(STOP), flags);
        return new Notification.Builder(this, "capture")
                .setSmallIcon(R.drawable.ic_caption)
                .setContentTitle("Capturing eligible VRChat playback")
                .setContentIntent(open)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Stop", stop).build())
                .build();
    }

    @Override
    public void onDestroy() {
        if (session != null) session.close();
        if (projection != null) {
            projection.unregisterCallback(projectionCallback);
            projection.stop();
        }
        running = false;
        super.onDestroy();
    }

    private final class Session {
        private final String address;
        private final String token;
        private final String language;
        private final String mode;
        private final AudioPlaybackCaptureConfiguration source;
        private final ArrayBlockingQueue<byte[]> queued = new ArrayBlockingQueue<>(1);
        private final Thread reader = new Thread(this::read, "playback-capture");
        private final Thread uploader = new Thread(this::upload, "caption-upload");
        private volatile boolean closed;
        private AudioRecord recorder;

        Session(Intent intent, AudioPlaybackCaptureConfiguration source) {
            this.source = source;
            address = intent.getStringExtra("address");
            token = intent.getStringExtra("token");
            language = intent.getStringExtra("language");
            mode = intent.getStringExtra("mode");
        }

        void start() {
            uploader.start();
            reader.start();
        }

        private void read() {
            try {
                int size = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                if (size <= 0) throw new IllegalStateException("Unsupported playback format");
                synchronized (this) {
                    if (closed) return;
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                        throw new SecurityException("Audio capture permission was revoked");
                    }
                    recorder = new AudioRecord.Builder().setAudioPlaybackCaptureConfig(source)
                            .setAudioFormat(new AudioFormat.Builder().setSampleRate(SAMPLE_RATE)
                                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                            .setBufferSizeInBytes(Math.max(size * 2, SAMPLE_RATE * 2))
                            .build();
                    recorder.startRecording();
                }
                while (!closed) {
                    byte[] chunk = new byte[CHUNK_BYTES];
                    int offset = 0;
                    boolean signal = false;
                    while (!closed && offset < chunk.length) {
                        int read = recorder.read(chunk, offset, Math.min(3200, chunk.length - offset),
                                AudioRecord.READ_BLOCKING);
                        if (read <= 0) throw new IllegalStateException("Playback stream disconnected");
                        for (int i = offset; !signal && i + 1 < offset + read; i += 2) {
                            short sample = (short) ((chunk[i] & 255) | (chunk[i + 1] << 8));
                            signal = Math.abs(sample) > 32;
                        }
                        offset += read;
                    }
                    if (closed) break;
                    if (signal) {
                        if (!queued.offer(chunk)) {
                            queued.poll();
                            queued.offer(chunk);
                        }
                    } else if (queued.isEmpty()) {
                        update("No eligible VRChat audio. Check that playback is active and capture is allowed.");
                    }
                }
            } catch (RuntimeException error) {
                main.post(() -> {
                    if (!closed) {
                        status = "Playback capture stopped. Reopen the panel to start again.";
                        stopSelf();
                    }
                });
            } finally {
                synchronized (this) {
                    if (recorder != null) {
                        recorder.release();
                        recorder = null;
                    }
                }
            }
        }

        private void upload() {
            while (!closed) {
                try {
                    Companion.submit(address, token, language, mode, queued.take());
                    update("Receiving VRChat playback");
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    return;
                } catch (Exception error) {
                    update(error.getMessage() != null && error.getMessage().startsWith("Linux capture")
                            ? error.getMessage() : "Could not send audio. Check the address, token and Wi-Fi.");
                }
            }
        }

        private void update(String message) {
            main.post(() -> {
                if (!closed) status = message;
            });
        }

        synchronized void close() {
            closed = true;
            uploader.interrupt();
            queued.clear();
            if (recorder != null && recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                try {
                    recorder.stop();
                } catch (IllegalStateException ignored) {
                    // The audio server may already have disconnected.
                }
            }
        }
    }
}

package sh.judge.singularity;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;

final class Companion {
    static String address(String value) {
        URI uri = URI.create(value.trim());
        String scheme = uri.getScheme();
        String path = uri.getPath();
        if (!("http".equals(scheme) || "https".equals(scheme)) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || !(path.isEmpty() || path.equals("/")) || uri.getPort() == 0
                || uri.getPort() > 65535) {
            throw new IllegalArgumentException("Use a companion address such as http://192.168.1.10:8765");
        }
        return scheme + "://" + uri.getRawAuthority();
    }

    static JSONArray latest(String address, String token) throws IOException, JSONException {
        return request(address + "/v1/latest", token, null, null, null);
    }

    static void submit(String address, String token, String language, String mode, byte[] pcm)
            throws IOException, JSONException {
        request(address + "/v1/audio", token, language, mode, pcm);
    }

    private static JSONArray request(String url, String token, String language, String mode, byte[] pcm)
            throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) URI.create(url).toURL().openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(3500);
            connection.setReadTimeout(pcm == null ? 4000 : 18000);
            connection.setRequestProperty("Authorization", "Bearer " + token);
            if (pcm != null) {
                connection.setDoOutput(true);
                connection.setRequestMethod("POST");
                connection.setFixedLengthStreamingMode(pcm.length);
                connection.setRequestProperty("Content-Type", "application/octet-stream");
                connection.setRequestProperty("X-Source-Language", language);
                connection.setRequestProperty("X-Caption-Mode", mode);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(pcm);
                }
            }
            int status = connection.getResponseCode();
            if (status == 429 && pcm != null) return new JSONArray();
            if (status == 409) throw new IOException("Linux capture is active. Use Monitor companion.");
            if (status != 200) {
                throw new IOException(status == 401 ? "Check the companion token." : "Companion returned HTTP " + status);
            }
            try (InputStream input = connection.getInputStream()) {
                ByteArrayOutputStream result = new ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (result.size() + count > 131072) throw new IOException("Companion response too large.");
                    result.write(buffer, 0, count);
                }
                JSONObject response = new JSONObject(result.toString(StandardCharsets.UTF_8.name()));
                if (response.getInt("version") != 1) throw new IOException("Unsupported companion protocol.");
                return response.getJSONArray("captions");
            }
        } finally {
            connection.disconnect();
        }
    }
}

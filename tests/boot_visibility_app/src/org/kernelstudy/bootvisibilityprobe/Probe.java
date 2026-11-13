package org.kernelstudy.bootvisibilityprobe;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.system.ErrnoException;
import android.system.OsConstants;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** Self-targeted, permission-free instrumentation. No app or system hooks. */
public final class Probe extends Instrumentation {
    private static final int LIMIT = 65536;
    private static final Map<String, Set<String>> FIELDS = new HashMap<>();
    static {
        FIELDS.put("verifiedbootstate", set("green", "yellow", "orange", "red"));
        FIELDS.put("vbmeta.device_state", set("locked", "unlocked"));
        FIELDS.put("flash.locked", set("0", "1"));
        FIELDS.put("veritymode", set("enforcing", "eio", "logging", "disabled", "panicking", "restart"));
        FIELDS.put("secureboot", set("0", "1", "true", "false"));
    }
    private static Set<String> set(String... values) { return new HashSet<>(Arrays.asList(values)); }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    private static String read(InputStream in) throws Exception {
        try (InputStream source = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024];
            int count;
            while ((count = source.read(buffer)) != -1) {
                if (out.size() + count > LIMIT) throw new IllegalArgumentException("too_large");
                out.write(buffer, 0, count);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }
    private static String readFile(String path) throws Exception { return read(new FileInputStream(path)); }
    private static String status(Throwable error) {
        for (Throwable p = error; p != null; p = p.getCause()) {
            if (p instanceof ErrnoException) {
                int errno = ((ErrnoException) p).errno;
                if (errno == OsConstants.EACCES || errno == OsConstants.EPERM) return "permission_denied";
                if (errno == OsConstants.ENOENT) return "unavailable";
            }
        }
        if (error instanceof SecurityException) return "permission_denied";
        if (error instanceof IllegalArgumentException) return "parse_or_size_error";
        return "read_failed";
    }
    private static JSONObject value(String field, String raw) throws Exception {
        String v = raw.trim().toLowerCase(java.util.Locale.ROOT);
        JSONObject result = new JSONObject();
        if (v.isEmpty()) return result.put("status", "unset_or_empty");
        if (!FIELDS.get(field).contains(v)) return result.put("status", "unrecognized_value");
        return result.put("status", "observed").put("value", v);
    }
    private static List<String> tokens(String text, boolean comments) {
        List<String> result = new ArrayList<>();
        StringBuilder token = new StringBuilder();
        char quote = 0;
        boolean started = false, escape = false;
        for (char c : text.toCharArray()) {
            if (escape) { token.append(c); escape = false; started = true; continue; }
            if (c == '\\' && quote != '\'') { escape = true; started = true; continue; }
            if (quote != 0) {
                if (c == quote) quote = 0; else token.append(c);
                continue;
            }
            if (c == '\'' || c == '"') { quote = c; started = true; continue; }
            if (comments && c == '#') break;
            if (Character.isWhitespace(c) || c == 0) {
                if (started) { result.add(token.toString()); token.setLength(0); started = false; }
            } else { token.append(c); started = true; }
        }
        if (quote != 0 || escape) throw new IllegalArgumentException("malformed_input");
        if (started) result.add(token.toString());
        return result;
    }
    private static void add(JSONObject fields, String key, String raw) throws Exception {
        if (!key.startsWith("androidboot.")) return;
        String name = key.substring("androidboot.".length());
        if (!FIELDS.containsKey(name)) return;
        JSONArray values = fields.optJSONArray(name);
        if (values == null) { values = new JSONArray(); fields.put(name, values); }
        values.put(value(name, raw));
    }
    private static JSONObject bootFile(String path, boolean bootconfig) throws Exception {
        JSONObject result = new JSONObject(), fields = new JSONObject();
        try {
            String text = readFile(path);
            if (bootconfig) {
                for (String line : text.split("\n")) {
                    int pos = line.indexOf('=');
                    if (pos < 0) continue;
                    String key = line.substring(0, pos).trim();
                    if (!key.startsWith("androidboot.") || !FIELDS.containsKey(key.substring(12))) continue;
                    List<String> values = tokens(line.substring(pos + 1), true);
                    add(fields, key, values.size() == 1 ? values.get(0) : "invalid");
                }
            } else {
                for (String token : tokens(text, false)) {
                    int pos = token.indexOf('=');
                    if (pos >= 0) add(fields, token.substring(0, pos), token.substring(pos + 1));
                }
            }
            result.put("status", "readable");
        } catch (Exception e) { result.put("status", status(e)); fields = new JSONObject(); }
        return result.put("fields", fields);
    }
    private static JSONObject property(String field) throws Exception {
        java.lang.Process child = null;
        try {
            child = new ProcessBuilder("/system/bin/getprop", "ro.boot." + field).start();
            if (!child.waitFor(3, TimeUnit.SECONDS)) return new JSONObject().put("status", "timeout");
            if (child.exitValue() != 0) return new JSONObject().put("status", "read_failed");
            return value(field, read(child.getInputStream()));
        } catch (Exception e) { return new JSONObject().put("status", status(e)); }
        finally { if (child != null) child.destroy(); }
    }
    @Override public void onStart() {
        Bundle output = new Bundle();
        try {
            String domain = readFile("/proc/self/attr/current").replace("\u0000", "").trim();
            if (!domain.matches("[A-Za-z0-9_:.,-]{1,128}")) domain = "unrecognized";
            int uid = Process.myUid();
            JSONObject context = new JSONObject().put("type", "android_app").put("uid", uid)
                .put("selinux_domain", domain).put("sdk", Build.VERSION.SDK_INT)
                .put("target_sdk", getTargetContext().getApplicationInfo().targetSdkVersion);
            if (uid < 10000 || !domain.startsWith("u:r:untrusted_app")) {
                output.putString("probe_status", "unexpected_execution_context");
                output.putString("report", new JSONObject().put("context", context).toString());
                finish(Activity.RESULT_CANCELED, output); return;
            }
            context.put("app_sandbox_observed", true);
            JSONObject props = new JSONObject();
            for (String name : FIELDS.keySet()) props.put(name, new JSONArray().put(property(name)));
            JSONObject sources = new JSONObject()
                .put("properties", new JSONObject().put("status", "collected").put("fields", props))
                .put("proc_cmdline", bootFile("/proc/cmdline", false))
                .put("proc_bootconfig", bootFile("/proc/bootconfig", true))
                .put("dt_bootargs", bootFile("/sys/firmware/devicetree/base/chosen/bootargs", false))
                .put("proc_dt_bootargs", bootFile("/proc/device-tree/chosen/bootargs", false));
            JSONObject report = new JSONObject().put("schema", 1).put("context", context).put("sources", sources)
                .put("hardware_lock_state", "not_determined").put("attestation", "not_requested");
            output.putString("probe_status", "ok");
            output.putString("report", report.toString());
            finish(Activity.RESULT_OK, output);
        } catch (Exception e) {
            output.putString("probe_status", "failed");
            output.putString("error_type", e.getClass().getSimpleName());
            finish(Activity.RESULT_CANCELED, output);
        }
    }
}

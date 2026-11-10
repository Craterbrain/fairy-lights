package app.fairy.builder

import android.content.Context
import android.net.Uri
import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * The page asks for the same /api/... paths it uses with builder.py; here a bridge answers them
 * (saved projects in the app's own folder, the library from the APK, uploads over Bluetooth).
 */
class Host(private val context: Context, private val uploader: Uploader) {
    private val projects = File(context.filesDir, "projects").apply { mkdirs() }

    @JavascriptInterface
    fun call(path: String, body: String): String = try {
        val uri = Uri.parse("http://host$path")
        when (uri.path) {
            "/api/state" -> state()
            "/api/projects" -> JSONArray((projects.listFiles { f -> f.extension == "json" } ?: emptyArray()).map { it.nameWithoutExtension }.sorted()).toString()
            "/api/save" -> save(JSONObject(body))
            "/api/load" -> load(uri.getQueryParameter("name") ?: "")
            "/api/library" -> asset("library/index.json") ?: "[]"
            "/api/library/item" -> libraryItem(uri.getQueryParameter("id") ?: "")
            "/api/upload" -> upload(JSONObject(body))
            "/api/power" -> power(JSONObject(body).getBoolean("on"))
            else -> error("not found")
        }
    } catch (e: Exception) {
        JSONObject().put("ok", false).put("error", e.message ?: e.javaClass.simpleName).toString()
    }

    private fun error(msg: String) = JSONObject().put("error", msg).toString()

    private fun state() = with(uploader.state) {
        JSONObject().put("busy", busy).put("progress", progress).put("total", total).put("message", message).put("error", error).toString()
    }

    private fun safeName(name: String): String {
        val n = name.replace(Regex("[^A-Za-z0-9 _.-]"), "").trim().trim('.')
        require(n.isNotEmpty()) { "project needs a name" }
        return n
    }

    private fun save(p: JSONObject): String {
        val name = safeName(p.getString("name")); p.put("name", name)
        File(projects, "$name.json").writeText(p.toString())
        return JSONObject().put("ok", true).put("name", name).toString()
    }

    private fun load(name: String): String {
        val f = File(projects, safeName(name) + ".json")
        return if (f.exists()) f.readText() else error("not found")
    }

    private fun asset(path: String): String? =
        try { context.assets.open(path).bufferedReader().use { it.readText() } } catch (e: java.io.IOException) { null }

    private fun libraryItem(id: String): String {
        if (id.contains("..") || id.startsWith("/")) return error("not found")
        return asset("library/$id.json") ?: error("not found")
    }

    private fun upload(p: JSONObject): String {
        val w = p.optInt("w", 40); val h = p.optInt("h", 20)
        val fr = p.getJSONArray("frames")
        val frames = (0 until fr.length()).map { i -> fr.getJSONArray(i).let { a -> IntArray(a.length()) { a.getInt(it) } } }
        val steps = Fairy.uploadSteps(frames, w, h, p.optInt("speed", 50), p.optInt("direction", 0), p.optBoolean("flipX"), p.optBoolean("flipY"))
        val ok = uploader.start("Uploading ${frames.size} frame(s)", steps)
        return JSONObject().put("ok", ok).put("error", if (ok) "" else "another Bluetooth job is running").toString()
    }

    private fun power(on: Boolean): String {
        val ok = uploader.start("Power " + if (on) "on" else "off", listOf(Step(Fairy.power(on), 150)))
        return JSONObject().put("ok", ok).toString()
    }
}

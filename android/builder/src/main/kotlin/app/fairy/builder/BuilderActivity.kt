package app.fairy.builder

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.WindowInsets
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebView

/** A WebView around the same editor page the browser version uses, with a native bridge for Bluetooth and storage. */
class BuilderActivity : Activity() {
    private lateinit var web: WebView

    private fun needed(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val missing = needed().filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)

        web = WebView(this)
        web.setBackgroundColor(Color.TRANSPARENT)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Host(this, Uploader(this)), "FairyHost")
        web.webChromeClient = object : WebChromeClient() {      // confirm() and alert() do nothing in a WebView without this
            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@BuilderActivity).setMessage(message)
                    .setPositiveButton("OK") { _, _ -> result.confirm() }.setNegativeButton("Cancel") { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }
            override fun onJsAlert(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@BuilderActivity).setMessage(message).setPositiveButton("OK") { _, _ -> result.confirm() }
                    .setOnCancelListener { result.confirm() }.show()
                return true
            }
        }
        web.setOnApplyWindowInsetsListener { v, insets ->               // keep clear of the status bar, nav bar and keyboard
            if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                v.setPadding(i.left, i.top, i.right, i.bottom)
            } else @Suppress("DEPRECATION") {
                v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(web)
        web.loadUrl("file:///android_asset/builder.html")
    }

    override fun onDestroy() { web.destroy(); super.onDestroy() }
}

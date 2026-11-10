package app.fairy.builder

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.Context
import android.os.Build
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** What the page polls: the same fields builder.py reports. */
class UploadState {
    @Volatile var busy = false
    @Volatile var progress = 0
    @Volatile var total = 0
    @Volatile var message = "Ready"
    @Volatile var error = ""
}

/** Finds the light, connects with a large MTU (the picture packets are 242 bytes), and plays a list of writes. */
@SuppressLint("MissingPermission")
class Uploader(private val context: Context) {
    val state = UploadState()

    /** Starts [steps] on a worker thread. Returns false if a job is already running. */
    @Synchronized fun start(title: String, steps: List<Step>): Boolean {
        if (state.busy) return false
        state.busy = true; state.progress = 0; state.total = steps.size; state.error = ""; state.message = title
        Thread {
            try {
                play(steps)
                state.message = "$title: done"
            } catch (e: Exception) {
                state.error = e.message ?: e.javaClass.simpleName
                state.message = "$title: failed"
            } finally {
                state.busy = false
            }
        }.start()
        return true
    }

    private fun play(steps: List<Step>) {
        val adapter = (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
        if (adapter == null || !adapter.isEnabled) throw IllegalStateException("Bluetooth is off")
        val device = findLight(adapter)
        val connected = CountDownLatch(1); val mtu = CountDownLatch(1); val services = CountDownLatch(1)
        var writeChar: BluetoothGattCharacteristic? = null
        val callback = object : BluetoothGattCallback() {
            override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
                if (newState == BluetoothProfile.STATE_CONNECTED) { connected.countDown(); g.requestMtu(247) }
                else if (newState == BluetoothProfile.STATE_DISCONNECTED) { connected.countDown(); mtu.countDown(); services.countDown() }
            }
            override fun onMtuChanged(g: BluetoothGatt, m: Int, status: Int) { mtu.countDown(); g.discoverServices() }
            override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
                writeChar = g.getService(UUID.fromString(Fairy.SERVICE))?.getCharacteristic(UUID.fromString(Fairy.WRITE))
                services.countDown()
            }
        }
        state.message = "Connecting to ${device.name}"
        val gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        try {
            if (!connected.await(15, TimeUnit.SECONDS)) throw IllegalStateException("Could not connect. Is another app holding the light?")
            if (!mtu.await(10, TimeUnit.SECONDS)) throw IllegalStateException("The light did not answer the packet-size request")
            if (!services.await(10, TimeUnit.SECONDS)) throw IllegalStateException("The light did not list its services")
            val c = writeChar ?: throw IllegalStateException("The light has no control characteristic")
            state.message = "Sending"
            steps.forEachIndexed { i, s ->
                write(gatt, c, s.data)
                state.progress = i + 1
                Thread.sleep(s.delayMs)
            }
        } finally {
            gatt.disconnect(); Thread.sleep(200); gatt.close()
        }
    }

    @Suppress("DEPRECATION")
    private fun write(g: BluetoothGatt, c: BluetoothGattCharacteristic, data: ByteArray) {
        repeat(40) {                                         // the stack says "busy" if we outrun it; wait and retry
            val ok = if (Build.VERSION.SDK_INT >= 33) {
                g.writeCharacteristic(c, data, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE) == BluetoothGatt.GATT_SUCCESS
            } else {
                c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE; c.value = data; g.writeCharacteristic(c)
            }
            if (ok) return
            Thread.sleep(25)
        }
        throw IllegalStateException("The light stopped accepting data (connection lost?)")
    }

    private fun findLight(adapter: android.bluetooth.BluetoothAdapter): BluetoothDevice {
        state.message = "Looking for the light"
        val found = CountDownLatch(1); var result: BluetoothDevice? = null
        val scan = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, r: ScanResult) {
                val name = r.scanRecord?.deviceName ?: r.device.name ?: return
                if (name.startsWith(Fairy.NAME_PREFIX)) { result = r.device; found.countDown() }
            }
        }
        val scanner = adapter.bluetoothLeScanner ?: throw IllegalStateException("Bluetooth scanner unavailable")
        scanner.startScan(scan)
        try { found.await(15, TimeUnit.SECONDS) } finally { scanner.stopScan(scan) }
        return result ?: throw IllegalStateException("No Hello Fairy light found. Close the vendor app and try again.")
    }
}

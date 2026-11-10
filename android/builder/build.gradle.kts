plugins {
    id("com.android.application")
}

android {
    namespace = "app.fairy.builder"
    compileSdk = 36
    defaultConfig {
        applicationId = "app.fairy.builder"
        minSdk = 29
        targetSdk = 36
        versionCode = 3
        versionName = "0.1.2"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].assets.srcDir(file("build/staged-assets"))
}

kotlin { jvmToolchain(17) }

// The editor page and the library live one folder up (they are shared with the browser version).
val stageAssets by tasks.registering(Sync::class) {
    from(rootProject.file("../builder.html"))
    from(rootProject.file("../library")) { into("library") }
    into(layout.buildDirectory.dir("staged-assets"))
}
tasks.configureEach { if (name.startsWith("merge") && name.endsWith("Assets")) dependsOn(stageAssets) }

dependencies {
    testImplementation("junit:junit:4.13.2")
}

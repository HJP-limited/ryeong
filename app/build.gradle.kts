plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    androidResources {
        noCompress += "onnx"
        noCompress += "tflite"
        noCompress += "task"
        noCompress += "litertlm"
    }
    namespace = "com.example.hjp"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.example.hjp"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += "arm64-v8a"
        }
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
    implementation("androidx.room:room-runtime:2.6.1")
    annotationProcessor("androidx.room:room-compiler:2.6.1")
    // EmbeddingGemma 실행용 공식 SDK — MediaPipe TextEmbedder는 이 모델을 못 읽는다 (메타데이터 없음)
    implementation("com.google.ai.edge.localagents:localagents-rag:0.3.0")
    // localagents-rag의 내부 proto 클래스가 이걸 필요로 하는데 SDK의 POM에 선언이 빠져 있어 직접 추가해야 한다
    // (NoClassDefFoundError: Lcom/google/protobuf/GeneratedMessageLite;)
    implementation("com.google.protobuf:protobuf-javalite:4.35.1")
    implementation("com.google.ai.edge.litertlm:litertlm-android:latest.release")
}

# ============================================================
# Общие
# ============================================================
-keepattributes *Annotation*
-keepattributes Signature
-keepattributes InnerClasses
-keepattributes EnclosingMethod
-keepattributes SourceFile,LineNumberTable

# Kotlin
-dontwarn kotlin.**
-dontwarn kotlinx.**

# ============================================================
# Gson — data-классы парсятся рефлексией по именам полей.
# Без -keep R8 удалит или переименует поля → JSON сломается.
# ============================================================
-keep class com.wms.client.api.** { *; }
-keep class com.wms.client.view.** { *; }
-keepclassmembers,allowobfuscation class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
-keep class com.google.gson.** { *; }
-dontwarn com.google.gson.**

# ============================================================
# OkHttp
# ============================================================
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**

# ============================================================
# zxing + journeyapps
# ============================================================
-keep class com.journeyapps.barcodescanner.** { *; }
-keep class com.google.zxing.** { *; }
-dontwarn com.google.zxing.**

# ============================================================
# Compose — R8 уже знает про compose, но оставим на случай
# ============================================================
-dontwarn androidx.compose.**

# ============================================================
# Прочее
# ============================================================
-keep class com.wms.client.MainActivity { *; }
-keep class com.wms.client.WmsViewModel { *; }
-keep class com.wms.client.Lang { *; }
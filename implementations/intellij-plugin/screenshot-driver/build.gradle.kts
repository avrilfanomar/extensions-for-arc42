import org.jetbrains.kotlin.gradle.dsl.KotlinVersion

// A development-only plugin that drives the IDE to capture the Marketplace screenshots. Only the parent project's
// runIdeForScreenshots task loads it -> ../screenshots/README.md
plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
}

kotlin {
    jvmToolchain(21)
    compilerOptions {
        apiVersion = KotlinVersion.KOTLIN_2_2
    }
}

dependencies {
    intellijPlatform {
        val localPath = providers.gradleProperty("platformLocalPath").orNull
        if (localPath != null) {
            local(localPath)
        } else {
            intellijIdea(providers.gradleProperty("platformVersion").get())
        }
    }
}

intellijPlatform {
    buildSearchableOptions = false
    instrumentCode = false
}

// Running a task such as publishPlugin from the parent project runs it here too: keep this plugin off the
// Marketplace and out of the checks.
tasks.matching {
    it.name in setOf("publishPlugin", "signPlugin", "verifyPluginSignature", "verifyPlugin", "runIde")
}.configureEach {
    enabled = false
}

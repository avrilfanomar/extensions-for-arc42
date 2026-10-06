import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.kotlin.gradle.dsl.KotlinVersion

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
}

kotlin {
    // IDEs of branch 253 run on Java 21 and bundle the Kotlin 2.2 standard library, which the plugin uses
    // -> https://plugins.jetbrains.com/docs/intellij/using-kotlin.html#kotlin-standard-library
    jvmToolchain(21)
    compilerOptions {
        apiVersion = KotlinVersion.KOTLIN_2_2
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")

    // https://plugins.jetbrains.com/docs/intellij/tools-intellij-platform-gradle-plugin-dependencies-extension.html
    intellijPlatform {
        val localPath = providers.gradleProperty("platformLocalPath").orNull
        if (localPath != null) {
            local(localPath)
        } else {
            intellijIdea(providers.gradleProperty("platformVersion").get())
        }
        testFramework(TestFrameworkType.Platform)
    }
}

intellijPlatform {
    pluginConfiguration {
        ideaVersion {
            sinceBuild = "253"
        }
    }
    // No settings pages to index, and no forms or Java sources to instrument.
    buildSearchableOptions = false
    instrumentCode = false
}

tasks.test {
    // The tests read the conformance cases and examples under the repository's extensions/ directory.
    systemProperty("arc42ext.repository", layout.projectDirectory.dir("../..").asFile.absolutePath)
}

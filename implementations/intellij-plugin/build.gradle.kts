import org.jetbrains.changelog.Changelog
import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.VerifyPluginTask
import org.jetbrains.kotlin.gradle.dsl.KotlinVersion

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.changelog")
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
        // The Marketplace shows the section of CHANGELOG.md for this version as the change notes.
        changeNotes = provider {
            changelog.renderItem(
                changelog.get(project.version.toString()).withHeader(false).withEmptySections(false),
                Changelog.OutputType.HTML,
            )
        }
    }
    pluginVerification {
        ides {
            recommended()
        }
        failureLevel = listOf(VerifyPluginTask.FailureLevel.COMPATIBILITY_PROBLEMS)
    }
    // Secrets come from the environment or ~/.gradle/gradle.properties, never from the repository -> PUBLISHING.md
    signing {
        certificateChain = providers.environmentVariable("CERTIFICATE_CHAIN")
        privateKey = providers.environmentVariable("PRIVATE_KEY")
        password = providers.environmentVariable("PRIVATE_KEY_PASSWORD")
    }
    publishing {
        token = providers.gradleProperty("intellijPlatformPublishingToken")
        channels = providers.gradleProperty("pluginChannel").map { listOf(it) }.orElse(listOf("default"))
    }
    // No settings pages to index, and no forms or Java sources to instrument.
    buildSearchableOptions = false
    instrumentCode = false
}

changelog {
    groups = listOf("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security", "Limitations")
    repositoryUrl = "https://github.com/avrilfanomar/extensions-for-arc42"
}

tasks.test {
    // The tests read the conformance cases and examples under the repository's extensions/ directory.
    systemProperty("arc42ext.repository", layout.projectDirectory.dir("../..").asFile.absolutePath)
}

// Screenshots for the Marketplace: a project with the triggers example, opened in an IDE that the screenshot
// driver plugin drives -> screenshots/README.md
val screenshotProject = layout.buildDirectory.dir("screenshot-project")

val prepareScreenshotProject by tasks.registering(Sync::class) {
    from("../../extensions/triggers/EN/example.adoc") {
        rename { "arc42.adoc" }
        into("docs")
    }
    into(screenshotProject)
}

intellijPlatformTesting.runIde.register("runIdeForScreenshots") {
    plugins {
        localPlugin(dependencies.project(":screenshot-driver"))
    }
    task {
        dependsOn(prepareScreenshotProject)
        args(screenshotProject.get().asFile.absolutePath)
        systemProperty("arc42ext.screenshots.dir", layout.projectDirectory.dir("screenshots").asFile.absolutePath)
        // Keep first-run dialogs from covering the IDE.
        systemProperty("idea.trust.all.projects", "true")
        systemProperty("jb.consents.confirmation.enabled", "false")
        systemProperty("jb.privacy.policy.text", "<!--999.999-->")
        systemProperty("ide.show.tips.on.startup.default.value", "false")
        systemProperty("ide.experimental.ui.onboarding", "false")
    }
}
